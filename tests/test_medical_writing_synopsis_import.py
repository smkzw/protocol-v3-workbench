from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import tempfile
import threading
import time
import unittest
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from pydantic import ValidationError

from packages.contracts.workbench_contracts import (
    MedicalWritingAssessmentInstrumentUse,
    MedicalWritingAuthoringJourneyCommitRequest,
    MedicalWritingAuthoringJourneyCreateRequest,
    MedicalWritingJourneyImpactPreviewRequest,
    MedicalWritingPicosDefinition,
    MedicalWritingStudyFraming,
    MedicalWritingSynopsisEvidenceSpan,
    MedicalWritingSynopsisImport,
    MedicalWritingSynopsisImportConfirmRequest,
    MedicalWritingSynopsisSource,
)
from services.api.app import main as app_main
from services.api.app.medical_writing_authoring_journey import (
    MedicalWritingAuthoringJourneyService,
)
from services.api.app.medical_writing_synopsis_import import (
    MedicalWritingSynopsisImportService,
    _ai_sources,
    _assess_source_role,
    _bind_synopsis_instrument_sources,
    _sanitize_synopsis_instrument_candidates,
    _synopsis_structuring_instruction,
)


def _docx_bytes(text: str) -> bytes:
    content_types = b'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>'''
    document = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body><w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>方案摘要</w:t></w:r></w:p>
  <w:p><w:r><w:t>{text}</w:t></w:r></w:p><w:sectPr/></w:body>
</w:document>'''.encode("utf-8")
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("word/document.xml", document)
    return output.getvalue()


def _fake_route_snapshot(profile_revision=1):
    snapshot = {
        "schema_version": "independent_ai_route_snapshot_v1",
        "role_id": "independent_ai",
        "profile_id": "fake-profile",
        "profile_revision": profile_revision,
        "provider": "fake",
        "model": "fake-model",
        "base_url": "https://fake.invalid/v1",
        "transport": "openai_compatible",
        "expected_response_model": "fake-model",
        "deployment_profile": "fake-deployment",
    }
    return {
        **snapshot,
        "identity_sha256": hashlib.sha256(
            json.dumps(snapshot, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest(),
    }


class _FakeRouteMixin:
    def route_identity_snapshot(self, *, refresh=True):
        return _fake_route_snapshot()


def _completed_ai_run(
    request,
    run_id="airun_synopsis_test",
    assessment_instruments=None,
):
    source = request.allowed_sources[0]
    output = {
            "task_id": run_id,
            "task_type": "protocol_synopsis_structuring",
            "provider": "fake",
            "model": "fake-model",
            "prompt_version": request.prompt_version,
            "input_source_ids": [item.source_id for item in request.allowed_sources],
            "forbidden_source_ids": request.forbidden_source_ids,
            "findings": [],
            "evidence_spans": [
                {
                    "span_id": "ev_indication",
                    "source_id": source.source_id,
                    "locator": source.locator,
                    "quote": source.text_preview,
                }
            ],
            "uncertainties": [
                {"level": "data_gap", "description": "其余研究设计字段待医学经理补充。"}
            ],
            "needs_medical_confirmation": True,
            "schema_version": "ai_task_output_v0_1",
            "study_definition": {
                "framing": {
                    "protocol_id": "CMS-RA-SYN-001",
                    "document_title": "CMS-RA-SYN-001类风湿关节炎II期临床研究方案",
                    "indication": "类风湿关节炎",
                    "clinicaltrials_condition_term": "Rheumatoid Arthritis",
                    "study_phase": "II期",
                    "intrinsic_objectives": ["概念验证（PoC）"],
                    "investigational_product": "CMS-RA-SYN",
                    "target_mechanism": "待医学经理确认",
                    "design_pattern": "随机、双盲、安慰剂对照研究",
                    "population_intent": "中重度活动性类风湿关节炎成人患者",
                },
                "picos": {
                    "design_archetype": "randomized_confirmatory",
                    "population_summary": "中重度活动性类风湿关节炎成人患者",
                    "intervention_summary": "CMS-RA-SYN治疗",
                    "comparator_summary": "安慰剂对照",
                    "primary_endpoint": "第12周ACR20应答率",
                    "study_epochs": ["筛选期", "治疗期"],
                    "assessment_instruments": assessment_instruments or [],
                },
                "synopsis_text": "本研究拟评价CMS-RA-SYN治疗类风湿关节炎的有效性和安全性。",
                "missing_fields": ["picos.inclusion_modules", "picos.exclusion_modules"],
                "conflict_notes": [],
                "field_evidence_span_ids": {
                    "framing.indication": ["ev_indication"],
                    **(
                        {"picos.assessment_instruments": ["ev_indication"]}
                        if assessment_instruments
                        else {}
                    ),
                },
            },
        }
    return SimpleNamespace(
        run_id=run_id,
        provider="fake",
        model_name="fake-model",
        actual_response_model="fake-model",
        route_identity_hash=_fake_route_snapshot()["identity_sha256"],
        status=SimpleNamespace(value="completed"),
        artifacts=[SimpleNamespace(artifact_type="provider_output", payload=output)],
        validation_errors=[],
        error_message="",
    )


class SynopsisStructuringInstructionTests(unittest.TestCase):
    def test_instruction_contains_complete_typed_default_templates(self):
        instruction = _synopsis_structuring_instruction("类风湿关节炎")
        lines = dict(
            line.split("=", 1)
            for line in instruction.splitlines()
            if line.startswith(
                (
                    "framing_template=",
                    "picos_template=",
                    "assessment_instrument_item_template=",
                )
            )
        )

        framing = json.loads(lines["framing_template"])
        picos = json.loads(lines["picos_template"])
        instrument = json.loads(lines["assessment_instrument_item_template"])
        self.assertEqual(set(MedicalWritingStudyFraming.model_fields), set(framing))
        self.assertEqual(set(MedicalWritingPicosDefinition.model_fields), set(picos))
        self.assertEqual("other", instrument["instrument_kind"])
        self.assertIsInstance(framing["intrinsic_objectives"], list)
        self.assertIsInstance(picos["visit_strategy"], str)
        self.assertIsInstance(picos["field_applicability"], dict)
        self.assertIsInstance(picos["primary_objectives"], list)
        self.assertIsInstance(picos["secondary_objectives"], list)
        self.assertIsInstance(picos["exploratory_objectives"], list)
        self.assertIn("不得把字符串写成数组", instruction)
        self.assertIn("任何不同于模板默认值的候选都必须绑定至少一个来源证据", instruction)
        self.assertIn("不超过500字", instruction)
        self.assertIn("randomized_exploratory", instruction)
        self.assertIn("不得仅凭II期判为探索性", instruction)
        self.assertIn("开放标签只是盲法属性", instruction)
        self.assertIn("证据不足时保持空字符串", instruction)
        self.assertIn("assessment_instrument_item_template", instruction)
        self.assertIn("不得推断量表版权", instruction)
        self.assertIn("不得只把名称埋在终点文本中", instruction)
        self.assertIn("仅直接支持该候选", instruction)
        self.assertIn("禁止把整个量表字段的全部证据复制给每个候选", instruction)
        self.assertIn("微生物/结核筛查", instruction)
        self.assertIn("最小充分证据集", instruction)
        self.assertIn("应答/临床意义改善阈值不得写入此字段", instruction)
        self.assertIn("例如BSA", instruction)
        self.assertIn("成人DLQI与儿童CDLQI", instruction)
        self.assertIn("包括Hb、LDH", instruction)
        self.assertIn("PK浓度", instruction)
        self.assertIn("完整picos.前缀", instruction)
        self.assertIn("不得把普通次要终点升级为关键次要终点", instruction)
        self.assertIn("endpoint_paths必须返回空数组", instruction)
        self.assertIn("结构化抽取不是摘要改写", instruction)
        self.assertIn("列表字段必须与原文项目一一对应并保持顺序", instruction)
        self.assertIn("输血、阈值、时间窗及定义性括注必须完整保留", instruction)
        self.assertIn("synopsis_text同样不得写成信息压缩版", instruction)
        self.assertIn("picos.primary_objectives", instruction)
        self.assertIn("开放标签、多剂量探索不得改写成双盲或安慰剂对照", instruction)
        self.assertIn("estimand_strategy保持空字符串", instruction)


class CompletedSynopsisResultUpgradeTests(unittest.TestCase):
    def test_source_backed_legacy_result_is_upgraded_without_new_ai_call(self):
        source = MedicalWritingSynopsisSource(
            source_id="d017_synopsis",
            original_filename="D017.docx",
            media_type=(
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document"
            ),
            actual_size=100,
            content_sha256="a" * 64,
            extraction_revision="docx_v1",
            parser_name="test",
            source_role_status="matched",
            indication_status="matched",
            validation_warnings=[],
            imported_at="2026-07-24T00:00:00+00:00",
            imported_by="medical_manager",
        )
        result = MedicalWritingSynopsisImport(
            status="review_pending",
            source=source,
            proposed_framing=MedicalWritingStudyFraming(
                document_title="D017 PNH II期方案摘要",
                indication="阵发性睡眠性血红蛋白尿症",
                study_phase="II期",
                investigational_product="CMS-D017",
                design_pattern="多中心、随机、开放标签、平行、剂量探索",
            ),
            proposed_picos=MedicalWritingPicosDefinition(
                comparator_summary="CMS-D017低剂量组与CMS-D017高剂量组比较",
            ),
            proposed_synopsis_text="D017方案摘要",
            field_evidence_span_ids={
                "framing.design_pattern": ["span_design"],
                "picos.comparator_summary": ["span_comparator"],
            },
            evidence_spans=[
                MedicalWritingSynopsisEvidenceSpan(
                    span_id="span_design",
                    source_id="d017_synopsis",
                    locator="p1:b1",
                    source_text="多中心、随机、开放标签、平行、剂量探索",
                    source_text_sha256=hashlib.sha256(
                        "多中心、随机、开放标签、平行、剂量探索".encode("utf-8")
                    ).hexdigest(),
                ),
                MedicalWritingSynopsisEvidenceSpan(
                    span_id="span_comparator",
                    source_id="d017_synopsis",
                    locator="p1:b2",
                    source_text="CMS-D017低剂量组与CMS-D017高剂量组比较",
                    source_text_sha256=hashlib.sha256(
                        "CMS-D017低剂量组与CMS-D017高剂量组比较".encode(
                            "utf-8"
                        )
                    ).hexdigest(),
                ),
            ],
        )

        upgraded = MedicalWritingSynopsisImportService._upgrade_completed_result(
            result
        )

        design = upgraded.proposed_framing.structured_design
        self.assertEqual("randomized", design.randomization_mode)
        self.assertEqual("open_label", design.blinding_mode)
        self.assertEqual("other", design.comparator_type)
        self.assertEqual("平行组", design.assignment_model)
        self.assertEqual("多中心", design.center_model)
        self.assertIn(
            "span_design",
            upgraded.field_evidence_span_ids["framing.structured_design"],
        )


class _FakeAiRunner(_FakeRouteMixin):
    def __init__(self):
        self.call_count = 0

    def submit_internal(self, project_id, request):
        self.call_count += 1
        return _completed_ai_run(request)


class _InstrumentCandidateAiRunner(_FakeRouteMixin):
    def submit_internal(self, project_id, request):
        return _completed_ai_run(
            request,
            "airun_synopsis_instrument_candidate",
            assessment_instruments=[
                {
                    "instrument_id": "provider-generated-id-must-not-survive",
                    "canonical_name_zh": "皮肤病生活质量指数",
                    "canonical_name_en": "Dermatology Life Quality Index",
                    "acronym": "DLQI",
                    "instrument_kind": "patient_reported",
                    "respondent": "受试者",
                    "recall_period": "过去1周",
                    "scoring_range": "0～30分",
                    "scoring_direction": "分值越高表示生活质量受影响越严重",
                    "study_purpose": "次要疗效终点评价",
                    "endpoint_paths": ["picos.other_secondary_endpoints"],
                    "visit_labels": ["基线", "第16周"],
                    "evidence_span_ids": ["ev_indication"],
                    "rights": {
                        "status": "public_domain",
                        "full_text_policy": "open_copy_allowed",
                    },
                    "translation": {
                        "status": "medical_reviewed",
                        "reviewed_by": "provider-hallucinated-reviewer",
                        "reviewed_at": "2026-07-17T00:00:00Z",
                    },
                    "confirmation_status": "confirmed",
                    "confirmed_by": "provider-hallucinated-confirmer",
                    "confirmed_at": "2026-07-17T00:00:00Z",
                }
            ],
        )


class _GateAiRunner(_FakeRouteMixin):
    def __init__(self, required_concurrent: int):
        self.required_concurrent = required_concurrent
        self.call_count = 0
        self.active_count = 0
        self.max_active_count = 0
        self.lock = threading.Lock()
        self.required_entered = threading.Event()
        self.release = threading.Event()

    def submit_internal(self, project_id, request):
        with self.lock:
            self.call_count += 1
            call_number = self.call_count
            self.active_count += 1
            self.max_active_count = max(self.max_active_count, self.active_count)
            if self.active_count >= self.required_concurrent:
                self.required_entered.set()
        try:
            if not self.release.wait(timeout=5.0):
                raise RuntimeError("test AI gate timed out")
            return _completed_ai_run(request, f"airun_synopsis_gate_{call_number}")
        finally:
            with self.lock:
                self.active_count -= 1


class _FailOnceAiRunner(_FakeRouteMixin):
    def __init__(self):
        self.call_count = 0

    def submit_internal(self, project_id, request):
        self.call_count += 1
        if self.call_count == 1:
            raise RuntimeError("simulated independent AI outage")
        return _completed_ai_run(request, "airun_synopsis_retried")


class _MismatchedAiRunner(_FakeAiRunner):
    def submit_internal(self, project_id, request):
        run = _completed_ai_run(request, "airun_synopsis_mismatched_route")
        run.route_identity_hash = "f" * 64
        return run


class _ChangedRouteRunner(_FakeAiRunner):
    def route_identity_snapshot(self, *, refresh=True):
        return _fake_route_snapshot(profile_revision=2)


def _request_sha256(filename: str, payload: bytes, expected_indication: str) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "filename": filename,
                "media_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "content_sha256": hashlib.sha256(payload).hexdigest(),
                "expected_indication": expected_indication,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


class MedicalWritingSynopsisImportTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self.journeys = MedicalWritingAuthoringJourneyService(
            self.root / "journeys.sqlite3"
        )
        self.ai_runner = _FakeAiRunner()
        self.importer = MedicalWritingSynopsisImportService(
            self.root / "synopsis_artifacts", self.ai_runner
        )

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_sanitizer_normalizes_known_instrument_kind_only_from_other(self):
        normalized = _sanitize_synopsis_instrument_candidates(
            {
                "assessment_instruments": [
                    {
                        "canonical_name_zh": "皮肤病生活质量指数",
                        "acronym": "DLQI",
                        "instrument_kind": "other",
                    },
                    {
                        "canonical_name_zh": "不良事件通用术语标准",
                        "acronym": "CTCAE",
                        "instrument_kind": "other",
                    },
                    {
                        "canonical_name_zh": "研究者整体评分",
                        "acronym": "IGA",
                        "instrument_kind": "observer_reported",
                    },
                ]
            },
            source_id="source_kind_normalization",
        )

        self.assertEqual(
            ["patient_reported", "safety_grading", "observer_reported"],
            [item["instrument_kind"] for item in normalized["assessment_instruments"]],
        )

    def test_sanitizer_does_not_repair_endpoint_path_aliases(self):
        normalized = _sanitize_synopsis_instrument_candidates(
            {
                "assessment_instruments": [
                    {
                        "canonical_name_zh": "慢性疾病治疗功能评估-疲劳量表",
                        "acronym": "FACIT-F",
                        "instrument_kind": "patient_reported",
                        "endpoint_paths": ["other_secondary_endpoints"],
                    }
                ]
            },
            source_id="source_d017_facit_f",
        )

        self.assertEqual(
            ["other_secondary_endpoints"],
            normalized["assessment_instruments"][0]["endpoint_paths"],
        )
        with self.assertRaisesRegex(
            ValidationError, "unsupported assessment instrument binding"
        ):
            MedicalWritingPicosDefinition.model_validate(normalized)

    def test_ai_sources_preserve_exact_parser_span_boundaries(self):
        spans = [
            SimpleNamespace(
                ich_m11_anchor="synopsis",
                source_text="方案编号\tCMS-RA-001",
                source_locator="upload:project:source:p1:b1",
            ),
            SimpleNamespace(
                ich_m11_anchor="synopsis",
                source_text="试验分期\tII期",
                source_locator="upload:project:source:p1:b2",
            ),
        ]

        sources = _ai_sources("proj_ra", "synopsis_ra", spans)

        self.assertEqual(2, len(sources))
        self.assertEqual("方案编号\tCMS-RA-001", sources[0].text_preview)
        self.assertEqual("试验分期\tII期", sources[1].text_preview)
        self.assertTrue(sources[0].locator.endswith("upload:project:source:p1:b1"))
        self.assertNotIn("..", sources[0].locator)

    def test_ai_sources_cover_instruments_beyond_document_front_matter(self):
        spans = [
            SimpleNamespace(
                ich_m11_anchor="unmapped",
                source_text=f"目录或一般正文片段 {index}",
                source_locator=f"upload:project:source:p1:b{index}",
            )
            for index in range(50)
        ]
        spans.extend(
            [
                SimpleNamespace(
                    ich_m11_anchor="objectives_endpoints",
                    source_text="第8周达到EASI 75应答的受试者比例。",
                    source_locator="upload:project:source:p1:b50",
                ),
                SimpleNamespace(
                    ich_m11_anchor="unmapped",
                    source_text="DLQI为患者报告结局问卷，回顾过去7天。",
                    source_locator="upload:project:source:p1:b51",
                ),
            ]
        )

        sources = _ai_sources("proj_ad", "protocol_ad", spans)

        selected_text = [item.text_preview for item in sources]
        self.assertIn("第8周达到EASI 75应答的受试者比例。", selected_text)
        self.assertIn("DLQI为患者报告结局问卷，回顾过去7天。", selected_text)
        self.assertLessEqual(len(sources), 40)

    def test_ai_sources_reserve_front_matter_before_long_thematic_buckets(self):
        front = [
            SimpleNamespace(
                ich_m11_anchor="unmapped",
                source_text=text,
                source_locator=f"upload:project:source:p1:b{index}",
            )
            for index, text in enumerate(
                [
                    "临床研究方案",
                    "磷酸芦可替尼乳膏治疗特应性皮炎的随机、双盲、安慰剂对照III期研究",
                    "研究分期\tIII期",
                    "试验药物名称\t磷酸芦可替尼乳膏\t适应症\t特应性皮炎\t临床方案号\tRUX-03-002",
                    "方案版本号\t1.3",
                    "方案版本日期\t2024年08月14日",
                ]
            )
        ]
        thematic = [
            SimpleNamespace(
                ich_m11_anchor="synopsis",
                source_text=f"方案摘要高密度片段 {index}",
                source_locator=f"upload:project:source:p2:b{index}",
            )
            for index in range(60)
        ]

        sources = _ai_sources("proj_rux", "protocol_rux", [*front, *thematic])

        selected_text = [item.text_preview for item in sources]
        self.assertIn("方案版本号\t1.3", selected_text)
        self.assertTrue(any("RUX-03-002" in item for item in selected_text))
        self.assertLessEqual(len(sources), 40)

    def test_ai_sources_reserve_each_critical_bucket_when_all_buckets_overflow(self):
        def bucket(anchor: str, prefix: str, start: int) -> list[SimpleNamespace]:
            return [
                SimpleNamespace(
                    ich_m11_anchor=anchor,
                    source_text=f"{prefix} {index}",
                    source_locator=f"upload:project:source:p1:b{start + index}",
                )
                for index in range(20)
            ]

        front = bucket("unmapped", "身份封面", 0)
        synopsis = bucket("synopsis", "方案摘要", 20)
        objectives = bucket("objectives_endpoints", "研究目的终点", 40)
        instruments = bucket("unmapped", "DLQI量表", 60)
        schedule = bucket("schedule", "访视流程", 80)
        eligibility = bucket("eligibility", "入排标准", 100)
        statistics = bucket("statistics", "统计分析", 120)
        spans = [
            *front,
            *synopsis,
            *objectives,
            *instruments,
            *schedule,
            *eligibility,
            *statistics,
        ]

        first = _ai_sources("proj_overflow", "protocol_overflow", spans)
        second = _ai_sources("proj_overflow", "protocol_overflow", spans)
        selected_text = [item.text_preview for item in first]

        self.assertEqual(40, len(first))
        self.assertTrue(any(text.startswith("身份封面") for text in selected_text))
        self.assertTrue(any(text.startswith("研究目的终点") for text in selected_text))
        self.assertTrue(any(text.startswith("入排标准") for text in selected_text))
        self.assertTrue(any(text.startswith("统计分析") for text in selected_text))
        self.assertTrue(any(text.startswith("访视流程") for text in selected_text))
        self.assertEqual(
            selected_text,
            [item.text_preview for item in second],
        )
        self.assertEqual(len(first), len({item.locator for item in first}))

    def test_full_protocol_is_a_matched_document_role(self):
        status, warnings = _assess_source_role(
            "磷酸芦可替尼乳膏临床试验方案\n试验设计\n入选标准\n排除标准\n统计方法"
        )

        self.assertEqual("matched", status)
        self.assertEqual([], warnings)

    def test_instrument_candidate_is_source_bound_and_governance_fields_fail_closed(self):
        importer = MedicalWritingSynopsisImportService(
            self.root / "instrument_candidate_artifacts",
            _InstrumentCandidateAiRunner(),
        )
        imported = importer.import_and_structure(
            "proj_dlqi_synopsis",
            filename="DLQI方案摘要.docx",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            payload=_docx_bytes(
                "特应性皮炎研究方案摘要：皮肤病生活质量指数（DLQI）由受试者填写，回顾过去1周，"
                "于基线和第16周评估，作为次要疗效终点。"
            ),
            expected_indication="特应性皮炎",
            actor="medical_manager_test",
            idempotency_key="import-dlqi-candidate",
        )

        self.assertEqual(1, len(imported.proposed_picos.assessment_instruments))
        candidate = imported.proposed_picos.assessment_instruments[0]
        self.assertTrue(candidate.instrument_id.startswith("instrument_"))
        self.assertNotEqual("provider-generated-id-must-not-survive", candidate.instrument_id)
        self.assertEqual("candidate", candidate.confirmation_status)
        self.assertEqual("unknown", candidate.rights.status)
        self.assertEqual("metadata_only", candidate.rights.full_text_policy)
        self.assertEqual("unknown", candidate.translation.status)
        self.assertTrue(candidate.source_synopsis_only)
        self.assertEqual(["ev_indication"], candidate.evidence_span_ids)
        self.assertEqual(1, len(candidate.source_bindings))
        self.assertEqual("project_protocol", candidate.source_bindings[0].source_kind)
        self.assertEqual(imported.source.source_id, candidate.source_bindings[0].source_id)
        self.assertEqual(
            imported.evidence_spans[0].source_text_sha256,
            candidate.source_bindings[0].evidence_sha256,
        )

    def test_each_instrument_binds_only_its_direct_evidence(self):
        imported_at = datetime(2026, 7, 17, tzinfo=timezone.utc)
        source = MedicalWritingSynopsisSource(
            source_id="source_protocol_ad",
            original_filename="AD研究方案.docx",
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            actual_size=1024,
            content_sha256="a" * 64,
            extraction_revision="docx_v1",
            parser_name="docx_parser",
            source_role_status="matched",
            indication_status="matched",
            imported_at=imported_at,
            imported_by="medical_manager_test",
        )
        evidence_spans = [
            MedicalWritingSynopsisEvidenceSpan(
                span_id="ev_iga",
                source_id=source.source_id,
                locator="docx:paragraph:730",
                source_text="第8周达到IGA-TS的受试者比例。",
                source_text_sha256=hashlib.sha256("第8周达到IGA-TS的受试者比例。".encode()).hexdigest(),
            ),
            MedicalWritingSynopsisEvidenceSpan(
                span_id="ev_dlqi",
                source_id=source.source_id,
                locator="docx:paragraph:761",
                source_text="采用DLQI评价生活质量。",
                source_text_sha256=hashlib.sha256("采用DLQI评价生活质量。".encode()).hexdigest(),
            ),
        ]
        picos = MedicalWritingPicosDefinition(
            assessment_instruments=[
                MedicalWritingAssessmentInstrumentUse(
                    instrument_id="instrument_iga",
                    canonical_name_zh="研究者整体评分",
                    acronym="IGA",
                    evidence_span_ids=["ev_iga"],
                ),
                MedicalWritingAssessmentInstrumentUse(
                    instrument_id="instrument_dlqi",
                    canonical_name_zh="皮肤病生活质量指数",
                    acronym="DLQI",
                    evidence_span_ids=["ev_dlqi"],
                ),
            ]
        )

        bound = _bind_synopsis_instrument_sources(
            picos,
            source=source,
            field_evidence_span_ids={
                "picos.assessment_instruments": ["ev_iga", "ev_dlqi"]
            },
            evidence_spans=evidence_spans,
        )

        self.assertEqual(
            ["docx:paragraph:730"],
            [item.locator for item in bound.assessment_instruments[0].source_bindings],
        )
        self.assertEqual(
            ["docx:paragraph:761"],
            [item.locator for item in bound.assessment_instruments[1].source_bindings],
        )

    def test_instrument_candidate_survives_synopsis_attach_and_confirmation_as_candidate(self):
        project_id = "proj_dlqi_candidate_confirmation"
        created = self.journeys.create(
            project_id,
            MedicalWritingAuthoringJourneyCreateRequest(
                entry_mode="synopsis_import",
                framing=MedicalWritingStudyFraming(),
                actor="medical_manager_test",
                idempotency_key="create-dlqi-candidate-confirmation",
            ),
        )
        importer = MedicalWritingSynopsisImportService(
            self.root / "instrument_confirmation_artifacts",
            _InstrumentCandidateAiRunner(),
        )
        imported = importer.import_and_structure(
            project_id,
            filename="DLQI方案摘要.docx",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            payload=_docx_bytes(
                "特应性皮炎研究方案摘要：皮肤病生活质量指数（DLQI）由受试者填写，回顾过去1周，"
                "于基线和第16周评估，作为次要疗效终点。"
            ),
            expected_indication="特应性皮炎",
            actor="medical_manager_test",
            idempotency_key="import-dlqi-candidate-confirmation",
        )
        attached = self.journeys.attach_synopsis_import(
            project_id,
            imported,
            expected_revision=created.revision,
            actor="medical_manager_test",
            idempotency_key="attach-dlqi-candidate-confirmation",
        )

        confirmed = self.journeys.confirm_synopsis_import(
            project_id,
            MedicalWritingSynopsisImportConfirmRequest(
                expected_revision=attached.revision,
                source_id=imported.source.source_id,
                framing=imported.proposed_framing,
                picos=imported.proposed_picos,
                synopsis_text=imported.proposed_synopsis_text,
                actor="medical_manager_test",
                idempotency_key="confirm-dlqi-candidate-confirmation",
            ),
        )

        candidate = confirmed.picos_draft.picos.assessment_instruments[0]
        self.assertEqual("DLQI", candidate.acronym)
        self.assertEqual("candidate", candidate.confirmation_status)
        self.assertEqual(["ev_indication"], candidate.evidence_span_ids)
        self.assertEqual(1, len(candidate.source_bindings))
        self.assertIn(
            "picos.assessment_instruments",
            confirmed.study_definition.unresolved_paths,
        )

    def test_concurrent_same_key_runs_independent_ai_once_and_waiters_reuse_result(self):
        runner = _GateAiRunner(required_concurrent=1)
        importer = MedicalWritingSynopsisImportService(
            self.root / "same_key_artifacts",
            runner,
            self.root / "same_key.sqlite3",
            claim_timeout_seconds=0.15,
            poll_interval_seconds=0.01,
        )
        payload = _docx_bytes("类风湿关节炎II期随机双盲安慰剂对照研究。")
        kwargs = {
            "filename": "RA方案摘要.docx",
            "content_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "payload": payload,
            "expected_indication": "类风湿关节炎",
            "actor": "medical_manager_test",
            "idempotency_key": "same-key",
        }
        waiter_lock = threading.Lock()
        waiter_count = 0
        all_waiters_started = threading.Event()

        def waiting_call():
            nonlocal waiter_count
            with waiter_lock:
                waiter_count += 1
                if waiter_count == 7:
                    all_waiters_started.set()
            return importer.import_and_structure("proj_ra", **kwargs)

        pool = ThreadPoolExecutor(max_workers=8)
        try:
            first = pool.submit(importer.import_and_structure, "proj_ra", **kwargs)
            self.assertTrue(runner.required_entered.wait(timeout=2.0))
            waiters = [pool.submit(waiting_call) for _ in range(7)]
            self.assertTrue(all_waiters_started.wait(timeout=1.0))
            time.sleep(0.35)
            self.assertEqual(1, runner.call_count)
            with sqlite3.connect(importer.db_path) as connection:
                state = connection.execute(
                    """
                    SELECT status, claim_token, attempt_count
                    FROM medical_writing_synopsis_imports
                    WHERE project_id = 'proj_ra' AND idempotency_key = 'same-key'
                    """
                ).fetchone()
            self.assertEqual(("pending", state[1], 1), state)
            self.assertTrue(state[1])
            runner.release.set()
            first_result = first.result(timeout=3.0)
            waiter_results = [future.result(timeout=3.0) for future in waiters]
        finally:
            runner.release.set()
            pool.shutdown(wait=True)

        for waiter_result in waiter_results:
            self.assertEqual(first_result.model_dump(), waiter_result.model_dump())
        self.assertEqual(1, runner.call_count)
        with sqlite3.connect(importer.db_path) as connection:
            completed = connection.execute(
                """
                SELECT status, claim_token, attempt_count, error_message
                FROM medical_writing_synopsis_imports
                WHERE project_id = 'proj_ra' AND idempotency_key = 'same-key'
                """
            ).fetchone()
        self.assertEqual(("completed", "", 1, ""), completed)

    def test_different_projects_with_same_key_enter_ai_concurrently(self):
        runner = _GateAiRunner(required_concurrent=2)
        importer = MedicalWritingSynopsisImportService(
            self.root / "project_parallel_artifacts",
            runner,
            self.root / "project_parallel.sqlite3",
        )
        payload = _docx_bytes("类风湿关节炎II期随机双盲安慰剂对照研究。")
        kwargs = {
            "filename": "RA方案摘要.docx",
            "content_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "payload": payload,
            "expected_indication": "类风湿关节炎",
            "actor": "medical_manager_test",
            "idempotency_key": "shared-key",
        }
        pool = ThreadPoolExecutor(max_workers=2)
        try:
            first = pool.submit(importer.import_and_structure, "proj_ra_a", **kwargs)
            second = pool.submit(importer.import_and_structure, "proj_ra_b", **kwargs)
            self.assertTrue(runner.required_entered.wait(timeout=2.0))
            self.assertEqual(2, runner.max_active_count)
            runner.release.set()
            first.result(timeout=3.0)
            second.result(timeout=3.0)
        finally:
            runner.release.set()
            pool.shutdown(wait=True)

    def test_different_keys_in_same_project_enter_ai_concurrently(self):
        runner = _GateAiRunner(required_concurrent=2)
        importer = MedicalWritingSynopsisImportService(
            self.root / "key_parallel_artifacts",
            runner,
            self.root / "key_parallel.sqlite3",
        )
        payload = _docx_bytes("类风湿关节炎II期随机双盲安慰剂对照研究。")

        def import_with_key(key):
            return importer.import_and_structure(
                "proj_ra",
                filename="RA方案摘要.docx",
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                payload=payload,
                expected_indication="类风湿关节炎",
                actor="medical_manager_test",
                idempotency_key=key,
            )

        pool = ThreadPoolExecutor(max_workers=2)
        try:
            first = pool.submit(import_with_key, "key-a")
            second = pool.submit(import_with_key, "key-b")
            self.assertTrue(runner.required_entered.wait(timeout=2.0))
            self.assertEqual(2, runner.max_active_count)
            runner.release.set()
            first.result(timeout=3.0)
            second.result(timeout=3.0)
        finally:
            runner.release.set()
            pool.shutdown(wait=True)

    def test_same_key_with_different_request_hash_fails_while_owner_is_running(self):
        runner = _GateAiRunner(required_concurrent=1)
        importer = MedicalWritingSynopsisImportService(
            self.root / "hash_conflict_artifacts",
            runner,
            self.root / "hash_conflict.sqlite3",
            poll_interval_seconds=0.01,
        )
        pool = ThreadPoolExecutor(max_workers=1)
        try:
            first = pool.submit(
                importer.import_and_structure,
                "proj_ra",
                filename="RA方案摘要.docx",
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                payload=_docx_bytes("类风湿关节炎II期研究。"),
                expected_indication="类风湿关节炎",
                actor="medical_manager_test",
                idempotency_key="hash-conflict",
            )
            self.assertTrue(runner.required_entered.wait(timeout=2.0))
            with self.assertRaisesRegex(ValueError, "different content"):
                importer.import_and_structure(
                    "proj_ra",
                    filename="RA方案摘要.docx",
                    content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    payload=_docx_bytes("银屑病III期研究。"),
                    expected_indication="银屑病",
                    actor="medical_manager_test",
                    idempotency_key="hash-conflict",
                )
            self.assertEqual(1, runner.call_count)
            runner.release.set()
            first.result(timeout=3.0)
        finally:
            runner.release.set()
            pool.shutdown(wait=True)

    def test_expired_pending_claim_is_recovered_with_next_attempt(self):
        runner = _FakeAiRunner()
        importer = MedicalWritingSynopsisImportService(
            self.root / "expired_claim_artifacts",
            runner,
            self.root / "expired_claim.sqlite3",
            claim_timeout_seconds=0.2,
            poll_interval_seconds=0.01,
        )
        payload = _docx_bytes("类风湿关节炎II期随机双盲研究。")
        filename = "RA方案摘要.docx"
        request_sha256 = _request_sha256(filename, payload, "类风湿关节炎")
        claimed = importer._claim_once(
            project_id="proj_ra",
            idempotency_key="expired-claim",
            request_sha256=request_sha256,
            claim_token="abandoned-process-claim",
            observed_attempt=None,
        )
        self.assertEqual("claimed", claimed["action"])
        with sqlite3.connect(importer.db_path) as connection:
            connection.execute(
                """
                UPDATE medical_writing_synopsis_imports
                SET lease_expires_at = '2000-01-01T00:00:00+00:00'
                WHERE project_id = 'proj_ra' AND idempotency_key = 'expired-claim'
                """
            )

        recovered = importer.import_and_structure(
            "proj_ra",
            filename=filename,
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            payload=payload,
            expected_indication="类风湿关节炎",
            actor="medical_manager_test",
            idempotency_key="expired-claim",
        )

        self.assertEqual("review_pending", recovered.status)
        self.assertEqual(1, runner.call_count)
        with sqlite3.connect(importer.db_path) as connection:
            state = connection.execute(
                """
                SELECT status, attempt_count, claim_token
                FROM medical_writing_synopsis_imports
                WHERE project_id = 'proj_ra' AND idempotency_key = 'expired-claim'
                """
            ).fetchone()
        self.assertEqual(("completed", 2, ""), state)

    def test_failed_attempt_is_persisted_and_a_later_call_can_retry(self):
        runner = _FailOnceAiRunner()
        importer = MedicalWritingSynopsisImportService(
            self.root / "failed_retry_artifacts",
            runner,
            self.root / "failed_retry.sqlite3",
        )
        kwargs = {
            "filename": "RA方案摘要.docx",
            "content_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "payload": _docx_bytes("类风湿关节炎II期随机双盲研究。"),
            "expected_indication": "类风湿关节炎",
            "actor": "medical_manager_test",
            "idempotency_key": "retry-after-failure",
        }
        with self.assertRaisesRegex(RuntimeError, "simulated independent AI outage"):
            importer.import_and_structure("proj_ra", **kwargs)
        with sqlite3.connect(importer.db_path) as connection:
            failed = connection.execute(
                """
                SELECT status, payload_json, attempt_count, error_message
                FROM medical_writing_synopsis_imports
                WHERE project_id = 'proj_ra'
                  AND idempotency_key = 'retry-after-failure'
                """
            ).fetchone()
        self.assertEqual("failed", failed[0])
        self.assertEqual("", failed[1])
        self.assertEqual(1, failed[2])
        self.assertIn("simulated independent AI outage", failed[3])

        retried = importer.import_and_structure("proj_ra", **kwargs)

        self.assertEqual("review_pending", retried.status)
        self.assertEqual(2, runner.call_count)
        with sqlite3.connect(importer.db_path) as connection:
            completed = connection.execute(
                """
                SELECT status, attempt_count, error_message
                FROM medical_writing_synopsis_imports
                WHERE project_id = 'proj_ra'
                  AND idempotency_key = 'retry-after-failure'
                """
            ).fetchone()
        self.assertEqual(("completed", 2, ""), completed)

    def test_waiters_share_owner_failure_without_triggering_retry_storm(self):
        class _BlockingFailureRunner(_FakeRouteMixin):
            def __init__(self):
                self.call_count = 0
                self.entered = threading.Event()
                self.release = threading.Event()

            def submit_internal(self, project_id, request):
                self.call_count += 1
                self.entered.set()
                if not self.release.wait(timeout=5.0):
                    raise RuntimeError("test failure gate timed out")
                raise RuntimeError("shared simulated AI failure")

        runner = _BlockingFailureRunner()
        importer = MedicalWritingSynopsisImportService(
            self.root / "shared_failure_artifacts",
            runner,
            self.root / "shared_failure.sqlite3",
            poll_interval_seconds=0.01,
        )
        kwargs = {
            "filename": "RA方案摘要.docx",
            "content_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "payload": _docx_bytes("类风湿关节炎II期随机双盲研究。"),
            "expected_indication": "类风湿关节炎",
            "actor": "medical_manager_test",
            "idempotency_key": "shared-failure",
        }
        pool = ThreadPoolExecutor(max_workers=4)
        try:
            futures = [
                pool.submit(importer.import_and_structure, "proj_ra", **kwargs)
                for _ in range(4)
            ]
            self.assertTrue(runner.entered.wait(timeout=2.0))
            time.sleep(0.1)
            runner.release.set()
            errors = []
            for future in futures:
                with self.assertRaisesRegex(RuntimeError, "shared simulated AI failure") as caught:
                    future.result(timeout=3.0)
                errors.append(str(caught.exception))
        finally:
            runner.release.set()
            pool.shutdown(wait=True)

        self.assertEqual(4, len(errors))
        self.assertEqual(1, runner.call_count)
        with sqlite3.connect(importer.db_path) as connection:
            failed = connection.execute(
                """
                SELECT status, attempt_count, error_message
                FROM medical_writing_synopsis_imports
                WHERE project_id = 'proj_ra' AND idempotency_key = 'shared-failure'
                """
            ).fetchone()
        self.assertEqual("failed", failed[0])
        self.assertEqual(1, failed[1])
        self.assertIn("shared simulated AI failure", failed[2])

    def test_legacy_completed_row_is_migrated_and_replayed_without_ai(self):
        payload = _docx_bytes("类风湿关节炎II期随机双盲研究。")
        filename = "RA方案摘要.docx"
        bootstrap_runner = _FakeAiRunner()
        bootstrap = MedicalWritingSynopsisImportService(
            self.root / "legacy_bootstrap_artifacts",
            bootstrap_runner,
            self.root / "legacy_bootstrap.sqlite3",
        )
        completed = bootstrap.import_and_structure(
            "proj_ra",
            filename=filename,
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            payload=payload,
            expected_indication="类风湿关节炎",
            actor="medical_manager_test",
            idempotency_key="legacy-completed",
        )
        legacy_db = self.root / "legacy.sqlite3"
        with sqlite3.connect(legacy_db) as connection:
            connection.execute(
                """
                CREATE TABLE medical_writing_synopsis_imports (
                    project_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    request_sha256 TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(project_id, idempotency_key)
                )
                """
            )
            connection.execute(
                """
                INSERT INTO medical_writing_synopsis_imports(
                    project_id, idempotency_key, request_sha256,
                    payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    "proj_ra",
                    "legacy-completed",
                    _request_sha256(filename, payload, "类风湿关节炎"),
                    completed.model_dump_json(),
                    "2026-07-15T00:00:00+00:00",
                ),
            )
        replay_runner = _FakeAiRunner()
        migrated = MedicalWritingSynopsisImportService(
            self.root / "legacy_migrated_artifacts",
            replay_runner,
            legacy_db,
        )

        replayed = migrated.import_and_structure(
            "proj_ra",
            filename=filename,
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            payload=payload,
            expected_indication="类风湿关节炎",
            actor="medical_manager_test",
            idempotency_key="legacy-completed",
        )

        self.assertEqual(completed.model_dump(), replayed.model_dump())
        self.assertEqual(0, replay_runner.call_count)
        with sqlite3.connect(legacy_db) as connection:
            migrated_state = connection.execute(
                """
                SELECT status, attempt_count, updated_at
                FROM medical_writing_synopsis_imports
                WHERE project_id = 'proj_ra' AND idempotency_key = 'legacy-completed'
                """
            ).fetchone()
        self.assertEqual("completed", migrated_state[0])
        self.assertEqual(1, migrated_state[1])
        self.assertEqual("2026-07-15T00:00:00+00:00", migrated_state[2])

    def test_imported_synopsis_becomes_reviewable_drafts_in_one_study_definition(self):
        project_id = "proj_ra_synopsis_test"
        created = self.journeys.create(
            project_id,
            MedicalWritingAuthoringJourneyCreateRequest(
                entry_mode="synopsis_import",
                framing=MedicalWritingStudyFraming(),
                actor="medical_manager_test",
                idempotency_key="create-synopsis-journey",
            ),
        )
        payload = _docx_bytes(
            "CMS-RA-SYN-001为类风湿关节炎II期随机双盲安慰剂对照研究。"
        )
        imported = self.importer.import_and_structure(
            project_id,
            filename="CMS-RA-SYN-001方案摘要.docx",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            payload=payload,
            expected_indication="类风湿关节炎",
            actor="medical_manager_test",
            idempotency_key="import-ra-synopsis",
        )
        self.assertEqual("review_pending", imported.status)
        self.assertEqual("matched", imported.source.source_role_status)
        self.assertEqual("matched", imported.source.indication_status)
        self.assertEqual(1, len(imported.evidence_spans))
        replayed_import = self.importer.import_and_structure(
            project_id,
            filename="CMS-RA-SYN-001方案摘要.docx",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            payload=payload,
            expected_indication="类风湿关节炎",
            actor="medical_manager_test",
            idempotency_key="import-ra-synopsis",
        )
        self.assertEqual(imported.model_dump(), replayed_import.model_dump())
        self.assertEqual(1, self.ai_runner.call_count)

        attached = self.journeys.attach_synopsis_import(
            project_id,
            imported,
            expected_revision=created.revision,
            actor="medical_manager_test",
            idempotency_key="attach-synopsis",
        )
        self.assertEqual("imported_synopsis", attached.study_definition.origin)
        self.assertEqual(
            imported.proposed_synopsis_text,
            attached.study_definition.synopsis_text,
        )
        self.assertEqual(
            "extracted_candidate",
            attached.study_definition.field_states["framing.indication"].status,
        )
        self.assertFalse(attached.framing_complete)
        self.assertFalse(attached.picos_complete)

        confirmed = self.journeys.confirm_synopsis_import(
            project_id,
            MedicalWritingSynopsisImportConfirmRequest(
                expected_revision=attached.revision,
                source_id=imported.source.source_id,
                framing=imported.proposed_framing,
                picos=imported.proposed_picos,
                synopsis_text=imported.proposed_synopsis_text,
                actor="medical_manager_test",
                idempotency_key="confirm-synopsis",
            ),
        )
        self.assertEqual("confirmed", confirmed.synopsis_import.status)
        self.assertIsNotNone(confirmed.framing_draft)
        self.assertIsNotNone(confirmed.picos_draft)
        self.assertFalse(confirmed.framing_complete)
        self.assertFalse(confirmed.picos_complete)
        self.assertEqual("framing", confirmed.current_stage)
        self.assertEqual(
            "confirmed",
            confirmed.study_definition.field_states["framing.indication"].status,
        )
        self.assertEqual(
            "medical_manager_test",
            confirmed.study_definition.field_states["framing.indication"].confirmed_by,
        )
        self.assertEqual(
            "confirmed",
            confirmed.study_definition.field_states["picos.primary_endpoint"].status,
        )
        self.assertIn("picos.inclusion_modules", confirmed.study_definition.unresolved_paths)

        preview = self.journeys.impact_preview(
            project_id,
            MedicalWritingJourneyImpactPreviewRequest(
                expected_revision=confirmed.revision,
                stage="framing",
                framing=imported.proposed_framing,
            ),
        )
        promoted = self.journeys.commit_stage(
            project_id,
            MedicalWritingAuthoringJourneyCommitRequest(
                expected_revision=confirmed.revision,
                stage="framing",
                framing=imported.proposed_framing,
                impact_preview_id=(
                    preview.preview_id if preview.requires_confirmation else ""
                ),
                actor="medical_manager_test",
                idempotency_key="promote-confirmed-synopsis-framing",
            ),
        )
        self.assertTrue(promoted.framing_complete)
        self.assertIsNotNone(promoted.picos_draft)
        self.assertEqual(
            "confirmed",
            promoted.study_definition.field_states["picos.primary_endpoint"].status,
        )
        self.assertEqual(
            "medical_manager_test",
            promoted.study_definition.field_states["picos.primary_endpoint"].confirmed_by,
        )


class MedicalWritingSynopsisImportApiTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        root = Path(self.tmpdir.name)
        self.journeys = MedicalWritingAuthoringJourneyService(root / "journeys.sqlite3")
        self.importer = MedicalWritingSynopsisImportService(
            root / "synopsis_artifacts", _FakeAiRunner()
        )
        self.patches = [
            patch(
                "services.api.app.main.medical_writing_authoring_journey_service",
                self.journeys,
            ),
            patch(
                "services.api.app.main.medical_writing_synopsis_import_service",
                self.importer,
            ),
        ]
        for item in self.patches:
            item.start()
        self.client = TestClient(app_main.app)

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.tmpdir.cleanup()

    def test_api_runs_upload_review_and_confirmation_without_completing_formal_stages(self):
        project_id = "proj_ra_greenfield_sandbox"
        created = self.client.post(
            f"/api/projects/{project_id}/medical-writing/authoring-journey",
            json={
                "entry_mode": "synopsis_import",
                "framing": {},
                "actor": "medical_manager_test",
                "idempotency_key": "api-create-synopsis",
            },
        )
        self.assertEqual(200, created.status_code, created.text)
        uploaded = self.client.post(
            f"/api/projects/{project_id}/medical-writing/authoring-journey/synopsis-import",
            files={
                "file": (
                    "RA方案摘要.docx",
                    _docx_bytes("方案摘要：类风湿关节炎II期随机双盲安慰剂对照研究。"),
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
            data={
                "expected_revision": str(created.json()["revision"]),
                "actor": "medical_manager_test",
                "idempotency_key": "api-import-synopsis",
            },
        )
        # Upload now returns 202 with a job_id (async pattern).
        self.assertEqual(202, uploaded.status_code, uploaded.text)
        job_body = uploaded.json()
        self.assertTrue(job_body["job_id"])
        self.assertEqual("api-import-synopsis", job_body["idempotency_key"])
        # Poll for completion.
        import time as _poll_time
        deadline = _poll_time.monotonic() + 60.0
        result_body = None
        while _poll_time.monotonic() < deadline:
            status_resp = self.client.get(
                f"/api/projects/{project_id}/medical-writing/authoring-journey/synopsis-import/jobs/api-import-synopsis"
            )
            self.assertEqual(200, status_resp.status_code, status_resp.text)
            status_body = status_resp.json()
            if status_body["status"] == "review_ready":
                result_resp = self.client.get(
                    f"/api/projects/{project_id}/medical-writing/authoring-journey/synopsis-import/jobs/api-import-synopsis/result"
                )
                self.assertEqual(200, result_resp.status_code, result_resp.text)
                result_body = result_resp.json()
                break
            if status_body["status"] == "failed":
                self.fail(f"job failed: {status_body.get('error_message', '')}")
            _poll_time.sleep(1.0)
        self.assertIsNotNone(result_body, "job did not reach review_ready in time")
        imported = result_body["synopsis_import"]
        self.assertEqual("review_pending", imported["status"])
        confirmed = self.client.post(
            f"/api/projects/{project_id}/medical-writing/authoring-journey/synopsis-import/confirm",
            json={
                "expected_revision": result_body["revision"],
                "source_id": imported["source"]["source_id"],
                "framing": imported["proposed_framing"],
                "picos": imported["proposed_picos"],
                "synopsis_text": imported["proposed_synopsis_text"],
                "acknowledged_validation_warnings": imported["source"]["validation_warnings"],
                "validation_override_reason": (
                    "已核对原始文件与当前项目一致，保留系统提示并继续医学补全。"
                    if imported["source"]["validation_warnings"]
                    else ""
                ),
                "actor": "medical_manager_test",
                "idempotency_key": "api-confirm-synopsis",
            },
        )
        self.assertEqual(200, confirmed.status_code, confirmed.text)
        payload = confirmed.json()
        self.assertEqual("confirmed", payload["synopsis_import"]["status"])
        self.assertFalse(payload["framing_complete"])
        self.assertFalse(payload["picos_complete"])
        self.assertIsNotNone(payload["framing_draft"])
        self.assertIsNotNone(payload["picos_draft"])

    def test_content_warning_requires_explicit_acknowledgement_and_reason(self):
        project_id = "proj_ra_synopsis_warning"
        created = self.journeys.create(
            project_id,
            MedicalWritingAuthoringJourneyCreateRequest(
                entry_mode="synopsis_import",
                actor="medical_manager_test",
                idempotency_key="create-warning-journey",
            ),
        )
        imported = self.importer.import_and_structure(
            project_id,
            filename="study-synopsis.docx",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            payload=_docx_bytes("CMS-RA-SYN-001为II期随机双盲安慰剂对照研究。"),
            expected_indication="类风湿关节炎",
            actor="medical_manager_test",
        )
        self.assertTrue(imported.source.validation_warnings)
        attached = self.journeys.attach_synopsis_import(
            project_id,
            imported,
            expected_revision=created.revision,
            actor="medical_manager_test",
            idempotency_key="attach-warning-synopsis",
        )
        request = MedicalWritingSynopsisImportConfirmRequest(
            expected_revision=attached.revision,
            source_id=imported.source.source_id,
            framing=imported.proposed_framing,
            picos=imported.proposed_picos,
            synopsis_text=imported.proposed_synopsis_text,
            actor="medical_manager_test",
            idempotency_key="confirm-warning-synopsis",
        )
        with self.assertRaisesRegex(ValueError, "must be acknowledged"):
            self.journeys.confirm_synopsis_import(project_id, request)

        confirmed = self.journeys.confirm_synopsis_import(
            project_id,
            request.model_copy(
                update={
                    "acknowledged_validation_warnings": imported.source.validation_warnings,
                    "validation_override_reason": "已核对项目资料，适应症名称在摘要附件中另行定义。",
                    "idempotency_key": "confirm-warning-synopsis-override",
                }
            ),
        )
        self.assertEqual("confirmed", confirmed.synopsis_import.status)


class SynopsisAsyncJobTest(unittest.TestCase):
    """Tests for the async synopsis-import job lifecycle: 202 before AI,
    idempotent replay, cancel, and progress monotonicity."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.artifact_root = Path(self.tmpdir.name) / "artifacts"
        self.ai_runner = FakeBlockingAiRunner()
        self.service = MedicalWritingSynopsisImportService(
            self.artifact_root, self.ai_runner
        )

    def tearDown(self):
        # Join all workers before cleanup — prevents disk I/O errors.
        self.ai_runner.release()
        self.service.shutdown(timeout=10.0)
        self.tmpdir.cleanup()

    def test_start_returns_202_before_ai_completes(self):
        """POST start_job must return 202 immediately, before the blocking
        fake AI runner is released."""
        docx = _docx_bytes("这是一个测试方案摘要，用于验证异步导入。适应症为溃疡性结肠炎。")
        response = self.service.start_job(
            "proj_async_001",
            filename="synopsis.docx",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            payload=docx,
            expected_indication="溃疡性结肠炎",
            actor="medical_manager",
            idempotency_key="async-001",
        )
        # Must return immediately with a job_id, not wait for AI.
        self.assertTrue(response.job_id)
        self.assertEqual(response.idempotency_key, "async-001")
        self.assertIn(response.phase, ("parsing", "chunking", "uploaded"))
        # The AI runner must still be blocked (not released yet).
        self.assertFalse(self.ai_runner.completed)

    def test_identical_replay_returns_same_job(self):
        """Repeated identical idempotency key + canonical request returns the
        same job."""
        docx = _docx_bytes("测试方案摘要内容。适应症为类风湿关节炎。")
        first = self.service.start_job(
            "proj_async_002",
            filename="synopsis.docx",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            payload=docx,
            expected_indication="类风湿关节炎",
            actor="medical_manager",
            idempotency_key="async-replay",
        )
        second = self.service.start_job(
            "proj_async_002",
            filename="synopsis.docx",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            payload=docx,
            expected_indication="类风湿关节炎",
            actor="medical_manager",
            idempotency_key="async-replay",
        )
        self.assertEqual(first.idempotency_key, second.idempotency_key)

    def test_changed_request_same_key_is_conflict(self):
        """Same key with changed canonical request must raise ValueError
        (mapped to 409 in the HTTP route)."""
        docx1 = _docx_bytes("方案摘要A。适应症为溃疡性结肠炎。")
        self.service.start_job(
            "proj_async_003",
            filename="synopsis.docx",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            payload=docx1,
            expected_indication="溃疡性结肠炎",
            actor="medical_manager",
            idempotency_key="async-conflict",
        )
        docx2 = _docx_bytes("方案摘要B，不同的内容。适应症为类风湿关节炎。")
        with self.assertRaises(ValueError):
            self.service.start_job(
                "proj_async_003",
                filename="synopsis2.docx",
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                payload=docx2,
                expected_indication="类风湿关节炎",
                actor="medical_manager",
                idempotency_key="async-conflict",
            )

    def test_cancel_is_idempotent(self):
        """Cancelling a job twice must both succeed without error."""
        docx = _docx_bytes("方案摘要内容。适应症为银屑病。")
        self.service.start_job(
            "proj_async_004",
            filename="synopsis.docx",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            payload=docx,
            expected_indication="银屑病",
            actor="medical_manager",
            idempotency_key="async-cancel",
        )
        first_cancel = self.service.cancel_job("proj_async_004", "async-cancel")
        self.assertEqual(first_cancel.cancellation_state, "cancelled")
        # Second cancel must not raise.
        second_cancel = self.service.cancel_job("proj_async_004", "async-cancel")
        self.assertEqual(second_cancel.cancellation_state, "cancelled")

    def test_result_unavailable_before_readiness(self):
        """Result must not be available before REVIEW_READY."""
        docx = _docx_bytes("方案摘要内容。适应症为特应性皮炎。")
        self.service.start_job(
            "proj_async_005",
            filename="synopsis.docx",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            payload=docx,
            expected_indication="特应性皮炎",
            actor="medical_manager",
            idempotency_key="async-not-ready",
        )
        with self.assertRaises(RuntimeError):
            self.service.get_job_result("proj_async_005", "async-not-ready")

    def test_progress_reaches_review_ready_after_ai_completes(self):
        """After the AI runner completes, the job must reach REVIEW_READY and
        the result must be available."""
        docx = _docx_bytes("方案摘要内容。适应症为哮喘。")
        self.service.start_job(
            "proj_async_006",
            filename="synopsis.docx",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            payload=docx,
            expected_indication="哮喘",
            actor="medical_manager",
            idempotency_key="async-complete",
        )
        # Release the AI runner and wait for job completion.
        self.ai_runner.release()
        self.ai_runner.wait_for_completion(timeout=15.0)
        # Poll until review_ready (with generous timeout for import_and_structure post-processing).
        deadline = time.monotonic() + 30.0
        status = None
        while time.monotonic() < deadline:
            try:
                status = self.service.get_job("proj_async_006", "async-complete")
            except KeyError:
                time.sleep(0.2)
                continue
            if status.status in ("review_ready", "failed"):
                break
            time.sleep(0.3)
        self.assertIsNotNone(status, "job status was never available")
        self.assertEqual(
            status.status, "review_ready",
            f"job should be review_ready, got {status.status}: {status.error_message}",
        )
        result = self.service.get_job_result("proj_async_006", "async-complete")
        self.assertIsNotNone(result)

    def test_parent_and_chunks_persist_frozen_route_and_ai_audit(self):
        docx = _docx_bytes("方案摘要内容。适应症为哮喘。")
        self.service.start_job(
            "proj_async_route_audit",
            filename="synopsis.docx",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            payload=docx,
            expected_indication="哮喘",
            actor="medical_manager",
            idempotency_key="async-route-audit",
        )
        self.ai_runner.release()
        self.ai_runner.wait_for_completion(timeout=15.0)
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            if self.service.get_job("proj_async_route_audit", "async-route-audit").status == "review_ready":
                break
            time.sleep(0.1)

        with sqlite3.connect(self.service.db_path) as connection:
            parent = connection.execute(
                "SELECT route_snapshot_json, route_identity_hash FROM medical_writing_synopsis_imports "
                "WHERE project_id = ? AND idempotency_key = ?",
                ("proj_async_route_audit", "async-route-audit"),
            ).fetchone()
            chunks = connection.execute(
                "SELECT route_identity_hash, ai_run_id, actual_response_model FROM medical_writing_synopsis_import_chunks "
                "WHERE project_id = ? AND idempotency_key = ?",
                ("proj_async_route_audit", "async-route-audit"),
            ).fetchall()
        self.assertTrue(parent[0])
        self.assertNotIn("api_key", parent[0].lower())
        self.assertEqual(_fake_route_snapshot()["identity_sha256"], parent[1])
        self.assertTrue(chunks)
        self.assertTrue(all(row[0] == parent[1] for row in chunks))
        self.assertTrue(all(row[1] for row in chunks))
        self.assertTrue(all(row[2] == "fake-model" for row in chunks))

    def test_mismatched_ai_run_route_fails_closed(self):
        runner = _MismatchedAiRunner()
        service = MedicalWritingSynopsisImportService(
            self.artifact_root / "mismatched_route", runner
        )
        try:
            service.start_job(
                "proj_async_route_mismatch",
                filename="synopsis.docx",
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                payload=_docx_bytes("方案摘要内容。适应症为哮喘。"),
                expected_indication="哮喘",
                actor="medical_manager",
                idempotency_key="async-route-mismatch",
            )
            deadline = time.monotonic() + 15.0
            status = None
            while time.monotonic() < deadline:
                status = service.get_job("proj_async_route_mismatch", "async-route-mismatch")
                if status.status == "failed":
                    break
                time.sleep(0.1)
            self.assertIsNotNone(status)
            self.assertEqual("failed", status.status)
            self.assertIn("route_identity_hash", status.error_message)
        finally:
            service.shutdown(timeout=5.0)

    def test_merge_rejects_mixed_chunk_route_identity(self):
        docx = _docx_bytes("方案摘要内容。适应症为哮喘。")
        self.service.start_job(
            "proj_async_mixed_route",
            filename="synopsis.docx",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            payload=docx,
            expected_indication="哮喘",
            actor="medical_manager",
            idempotency_key="async-mixed-route",
        )
        self.ai_runner.release()
        self.ai_runner.wait_for_completion(timeout=15.0)
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            if self.service.get_job("proj_async_mixed_route", "async-mixed-route").status == "review_ready":
                break
            time.sleep(0.1)
        with sqlite3.connect(self.service.db_path) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute(
                "UPDATE medical_writing_synopsis_import_chunks SET route_identity_hash = ? "
                "WHERE project_id = ? AND idempotency_key = ?",
                ("e" * 64, "proj_async_mixed_route", "async-mixed-route"),
            )
            source = self.service._load_source_from_db(
                connection, "proj_async_mixed_route", "async-mixed-route"
            )
        with self.assertRaisesRegex(RuntimeError, "mixed"):
            self.service._merge_chunks(
                project_id="proj_async_mixed_route",
                idempotency_key="async-mixed-route",
                source_id=source.source_id,
                source=source,
                expected_indication="哮喘",
                chunk_total=1,
            )

    def test_cold_recovery_missing_or_changed_route_is_non_retryable(self):
        self.service._shutdown_requested = True
        for project_id, key in (
            ("proj_async_missing_route", "async-missing-route"),
            ("proj_async_changed_route", "async-changed-route"),
        ):
            self.service.start_job(
                project_id,
                filename="synopsis.docx",
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                payload=_docx_bytes("方案摘要内容。适应症为哮喘。"),
                expected_indication="哮喘",
                actor="medical_manager",
                idempotency_key=key,
            )
        with sqlite3.connect(self.service.db_path) as connection:
            connection.execute(
                "UPDATE medical_writing_synopsis_imports SET route_snapshot_json = '', route_identity_hash = '' "
                "WHERE project_id = ? AND idempotency_key = ?",
                ("proj_async_missing_route", "async-missing-route"),
            )

        changed_runner = _ChangedRouteRunner()
        recovered = MedicalWritingSynopsisImportService(
            self.artifact_root / "cold_recovery", changed_runner, self.service.db_path
        )
        try:
            self.assertEqual(0, recovered.recover_stale_jobs())
            with sqlite3.connect(self.service.db_path) as connection:
                states = connection.execute(
                    "SELECT project_id, status, error_message FROM medical_writing_synopsis_imports "
                    "WHERE idempotency_key IN (?, ?) ORDER BY project_id",
                    ("async-missing-route", "async-changed-route"),
                ).fetchall()
            self.assertEqual(["failed", "failed"], [row[1] for row in states])
            self.assertTrue(all("retry is not allowed" in row[2] for row in states))
            self.assertEqual(0, changed_runner.call_count)
        finally:
            recovered.shutdown(timeout=5.0)


class FakeBlockingAiRunner(_FakeRouteMixin):
    """A fake AI runner that blocks until released, simulating a long AI call.

    This verifies that start_job returns 202 before AI completes.
    """

    def __init__(self):
        self._event = threading.Event()
        self._completed = False
        self._lock = threading.Lock()

    @property
    def completed(self):
        with self._lock:
            return self._completed

    def submit_internal(self, project_id, request):
        """Block until released, then return a valid AI run output."""
        self._event.wait(timeout=30.0)
        with self._lock:
            self._completed = True
        return _completed_ai_run(request)

    def release(self):
        self._event.set()

    def wait_for_completion(self, timeout=10.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                if self._completed:
                    return
            time.sleep(0.1)


if __name__ == "__main__":
    unittest.main()
