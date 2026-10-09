"""新纪元第2轮修订 P0-A：全文初稿装配完整性确定性门（根治 NEW-13/NEW-14
跨节重复装配族）。

现场（深度分析·第1轮实证）：r10-A/export.docx 9.2/9.3/9.4 三节正文为逐字
节相同的 CMH 段——生成层校验只比 section_id 序列（_execute_chunk 的
actual_ids != expected_ids），不查内容与标题相关性、不查跨节重复；模型违反
prompt 指令时全链（生成→采纳→导出）无一处拦截。

三层确定性门（反例先红）：
T1 生成层（_execute_chunk）：同批输出内归一化后 >80 字相同正文出现于 ≥2 节
   → 拒收（RuntimeStoreError 点名节号），消息含『未通过校验』以落入既有
   validation 重试预算（重试仍犯→批次跳过点名，走 P0-25 既有降级通道）；
T2 采纳层（adopt）：对 target_sections 全集（剔除缺口节）做重复扫描，
   重复即拒绝采纳并点名节号；
T3 导出层（_export_placeholder_report）：跨节重复段落计入缺口
   （『章节内容装配重复』+点名节号）→ 草案-N 强制；
正例（各节正文互异、共享 <80 字的通用短语）不误伤。
"""
from __future__ import annotations

import hashlib
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]

_DUP_BODY = (
    "主要终点将采用CMH检验比较两组应答者的比例，检验水准取单侧0.025，"
    "并按中心分层进行敏感性分析；关键次要终点按预先设定的检验顺序逐级检验，"
    "以控制整体I类错误率，全部推断均基于全分析集开展。"
)
_UNIQUE_TAIL_A = "本节另载明数据录入与时点安排的特有约定A。"
_UNIQUE_TAIL_B = "本节另载明数据录入与时点安排的特有约定B。"
_UNIQUE_TAIL_C = "本节另载明数据录入与时点安排的特有约定C。"


def _sections(*specs):
    return [
        {
            "section_id": section_id,
            "content_status": "complete",
            "proposal_text": text,
            "rationale": "r",
            "evidence_span_ids": ["ev_1"],
            "evidence_bindings": [],
            "decision_items": [],
            "missing_source_classes": [],
            "gap_items": [],
        }
        for section_id, text in specs
    ]


class DuplicateDetectorTests(unittest.TestCase):
    def _find(self, sections):
        from services.api.app.medical_writing_full_draft import (
            find_full_draft_duplicate_sections,
        )

        return find_full_draft_duplicate_sections(sections)

    def test_same_body_across_three_sections_is_named(self) -> None:
        sections = _sections(
            ("sec_9_2", _DUP_BODY + _UNIQUE_TAIL_A),
            ("sec_9_3", _DUP_BODY + _UNIQUE_TAIL_B),
            ("sec_9_4", _DUP_BODY + _UNIQUE_TAIL_C),
        )
        duplicates = self._find(sections)
        self.assertTrue(duplicates)
        named = {sid for ids in duplicates.values() for sid in ids}
        self.assertEqual({"sec_9_2", "sec_9_3", "sec_9_4"}, named)

    def test_whitespace_variant_normalizes_to_duplicate(self) -> None:
        sections = _sections(
            ("sec_a", _DUP_BODY.replace("，", "，\n")),
            ("sec_b", _DUP_BODY.replace("，", "， ")),
        )
        self.assertTrue(self._find(sections))

    def test_unique_sections_are_not_flagged(self) -> None:
        sections = _sections(
            ("sec_a", _DUP_BODY + _UNIQUE_TAIL_A),
            ("sec_b", _DUP_BODY[:60] + _UNIQUE_TAIL_B),
            ("sec_c", _UNIQUE_TAIL_C),
        )
        self.assertEqual({}, self._find(sections))

    def test_shared_short_phrase_not_flagged(self) -> None:
        short = "本研究为随机双盲安慰剂对照设计。"
        sections = _sections(
            ("sec_a", short + "A节独有正文，叙述该节专属的方法学安排与边界条件，供审阅。"),
            ("sec_b", short + "B节独有正文，叙述该节专属的方法学安排与边界条件，供审阅。"),
        )
        self.assertEqual({}, self._find(sections))


class ChunkGateTests(unittest.TestCase):
    """_execute_chunk 同批跨节重复 → 拒收（validation 预算类，重试仍犯则
    跳过点名——消息须含『未通过校验』以落入 classify 的 validation 类）。"""

    def _service_with_output(self, sections):
        from services.api.app.medical_writing_full_draft import (
            FULL_DRAFT_PROMPT_VERSION,
        )
        from services.api.app.ai_gateway import AiTaskType
        from packages.contracts.workbench_contracts import (
            AiTaskArtifact,
            AiTaskRun,
            AiTaskRunStatus,
        )

        payload = {
            "task_id": "run_dup",
            "task_type": AiTaskType.PROTOCOL_FULL_DRAFT.value,
            "provider": "buddy",
            "model": "deepseek-v4-pro",
            "prompt_version": FULL_DRAFT_PROMPT_VERSION,
            "input_source_ids": ["s1"],
            "forbidden_source_ids": [],
            "findings": [],
            "evidence_spans": [],
            "uncertainties": [],
            "needs_medical_confirmation": True,
            "schema_version": "ai_task_output_v0_1",
            "full_draft": {"sections": sections},
        }
        now = datetime.now(timezone.utc)
        runner = SimpleNamespace(
            submit_internal=lambda project_id, request: AiTaskRun(
                run_id="run_dup",
                project_id=project_id,
                module="medical_writing",
                task_type=AiTaskType.PROTOCOL_FULL_DRAFT.value,
                purpose="full draft",
                status=AiTaskRunStatus.COMPLETED,
                provider="buddy",
                model_name="deepseek-v4-pro",
                ai_gateway_status="configured",
                request_origin="trusted_server_source",
                data_classification="confidential_clinical_document",
                deployment_profile="approved_private_documents",
                prompt_version=FULL_DRAFT_PROMPT_VERSION,
                artifacts=[AiTaskArtifact(artifact_id="a1", artifact_type="provider_output", payload=payload)],
                created_at=now,
                updated_at=now,
            )
        )
        source = SimpleNamespace(
            source_id="s1",
            source_type="current_project_study_definition",
            locator="study_definition:sd:1",
            text_preview="x",
        )
        return SimpleNamespace(
            repo=SimpleNamespace(project_id="proj_dup"),
            ai_task_runner=runner,
            _policy_identity=lambda task_type="medical_writing_revision": {"provider_name": "buddy", "model_name": "deepseek-v4-pro", "route_identity_hash": "h"},
            _current_project_study_definition_source=lambda protocol, section: source,
            _company_corpus_sources=lambda *args: [],
            _shared_corpus_sources=lambda *args: [],
        )

    def _execute(self, service, chunk_ids):
        from services.api.app.medical_writing_full_draft import (
            MedicalWritingFullDraftService,
        )

        full = MedicalWritingFullDraftService(
            service_resolver=lambda project_id: service,
            artifact_root=Path(ROOT / "_tmp_dup_gate_artifacts"),
        )
        # 冻结来源清单校验与本门无关：桩掉来源装配，聚焦重复门本身。
        from packages.contracts.workbench_contracts import AiTaskSourceRef

        full._sources_for_chunk = lambda svc, project_id, descriptor, chunk: [
            AiTaskSourceRef(
                source_id="s1",
                source_type="current_project_study_definition",
                title="已确认研究事实",
                locator="study_definition:sd:1",
                text_preview="x",
                project_id="proj_dup",
                module="medical_writing",
            )
        ]
        descriptor = {
            "digest": "d0",
            "minimum_body_chars": 1,
            "decision_path_owners": {},
            "section_ids": chunk_ids,
        }
        chunk = [
            {
                "section_id": sid,
                "heading": "统计",
                "section_number": "9",
                "node_kind": "section",
                "body_text": "",
            }
            for sid in chunk_ids
        ]
        return MedicalWritingFullDraftService._execute_chunk(
            full, service, "proj_dup", descriptor, chunk
        )

    def test_duplicated_chunk_output_is_rejected_with_section_names(self) -> None:
        service = self._service_with_output(
            _sections(
                ("sec_9_2", _DUP_BODY + _UNIQUE_TAIL_A),
                ("sec_9_3", _DUP_BODY + _UNIQUE_TAIL_B),
                ("sec_9_4", _DUP_BODY + _UNIQUE_TAIL_C),
            )
        )
        with self.assertRaises(RuntimeStoreError) as refused:
            self._execute(service, ["sec_9_2", "sec_9_3", "sec_9_4"])
        message = str(refused.exception)
        self.assertIn("未通过校验", message)
        for section_id in ("sec_9_2", "sec_9_3", "sec_9_4"):
            self.assertIn(section_id, message)

    def test_distinct_chunk_output_passes(self) -> None:
        service = self._service_with_output(
            _sections(
                ("sec_9_2", _DUP_BODY + _UNIQUE_TAIL_A),
                ("sec_9_3", _DUP_BODY[:70] + _UNIQUE_TAIL_B),
            )
        )
        output, _run, _sources = self._execute(service, ["sec_9_2", "sec_9_3"])
        self.assertEqual(2, len((output.get("full_draft") or {}).get("sections") or []))


from services.api.app.medical_writing_full_draft import RuntimeStoreError  # noqa: E402


class AdoptGateTests(unittest.TestCase):
    def _artifact(self, sections_spec):
        source_id = "study_definition_fake"
        locator = "study_definition:sd_fake:revision:1"
        quote = "适应症：哮喘"
        sections = []
        targets = []
        for section_id, text in sections_spec:
            sections.append(
                {
                    "section_id": section_id,
                    "content_status": "complete",
                    "proposal_text": text,
                    "rationale": "r",
                    "review_level": "informational",
                    "evidence_span_ids": ["ev_1"],
                    "source_ids": [source_id],
                    "evidence_bindings": [
                        {
                            "span_id": "ev_1",
                            "source_id": source_id,
                            "locator": locator,
                            "quote": quote,
                            "quote_sha256": hashlib.sha256(quote.encode("utf-8")).hexdigest(),
                        }
                    ],
                    "decision_items": [],
                    "missing_source_classes": [],
                    "gap_items": [],
                }
            )
            targets.append(
                {
                    "section_id": section_id,
                    "body_block_id": f"b_{section_id}",
                    "expected_revision": 0,
                    "body_sha256": hashlib.sha256("".encode("utf-8")).hexdigest(),
                }
            )
        return {
            "schema_version": "protocol_full_draft_artifact_v10",
            "document_id": "doc_full_draft_fake",
            "document_version": "0.1",
            "study_definition": {
                "id": "sd_fake",
                "revision": 1,
                "sha256": "a" * 64,
            },
            "source_bindings": [
                {"source_id": source_id, "locator": locator}
            ],
            "sections": sections,
            "target_sections": targets,
        }

    def _adopt(self, artifact):
        import tempfile

        from services.api.app.medical_writing_full_draft import (
            MedicalWritingFullDraftService,
        )
        from tests.test_medical_writing_full_draft import _FakeRepo

        repo = _FakeRepo()
        for section in artifact["target_sections"]:
            block_id = section["body_block_id"]
            repo.working[section["section_id"]] = SimpleNamespace(
                revision=0,
                content_blocks=[{"block_id": block_id, "block_type": "paragraph", "text": ""}],
            )
        source = SimpleNamespace(
            source_id="study_definition_fake",
            source_type="current_project_study_definition",
            locator="study_definition:sd_fake:revision:1",
            text_preview="适应症：哮喘",
        )
        service = SimpleNamespace(
            repo=repo,
            ai_task_runner=SimpleNamespace(),
            _policy_identity=lambda task_type="medical_writing_revision": {},
            _current_project_study_definition_source=lambda protocol, section: source,
            _company_corpus_sources=lambda *args: [],
            _shared_corpus_sources=lambda *args: [],
        )
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        full = MedicalWritingFullDraftService(
            service_resolver=lambda project_id: service,
            artifact_root=Path(tmp.name),
        )
        full.read_artifact = lambda project_id, job: artifact
        job = SimpleNamespace(job_id="job_dup")
        return full.adopt("proj_full_draft_fake", job)

    def test_duplicate_across_target_sections_blocks_adoption_with_names(self) -> None:
        artifact = self._artifact(
            (
                ("sec_9_2", _DUP_BODY + _UNIQUE_TAIL_A),
                ("sec_9_3", _DUP_BODY + _UNIQUE_TAIL_B),
                ("sec_9_4", _DUP_BODY + _UNIQUE_TAIL_C),
            )
        )
        with self.assertRaises(RuntimeStoreError) as refused:
            self._adopt(artifact)
        message = str(refused.exception)
        self.assertIn("重复", message)
        self.assertIn("未采纳", message)
        for section_id in ("sec_9_2", "sec_9_3", "sec_9_4"):
            self.assertIn(section_id, message)

    def test_distinct_sections_adopt_cleanly(self) -> None:
        artifact = self._artifact(
            (
                ("sec_9_2", _DUP_BODY + _UNIQUE_TAIL_A),
                ("sec_9_3", _DUP_BODY[:70] + _UNIQUE_TAIL_B),
            )
        )
        result = self._adopt(artifact)
        self.assertEqual(2, result["adopted_count"])


class ExportGateTests(unittest.TestCase):
    def _report(self, sections_spec):
        from services.api.app.main import _export_placeholder_report
        from packages.contracts.workbench_contracts import (
            ProtocolDocument,
            ProtocolSection,
        )

        document = ProtocolDocument(
            document_id="doc_dup_gate",
            project_id="proj_dup_gate",
            protocol_id="CMS-DUP",
            version="1.0",
            sections=[
                ProtocolSection(
                    section_id=section_id,
                    document_id="doc_dup_gate",
                    heading=f"统计{index}",
                    section_number=number,
                    content_blocks=[
                        {
                            "block_id": f"b_{section_id}",
                            "block_type": "paragraph",
                            "text": text,
                        }
                    ],
                )
                for index, (section_id, number, text) in enumerate(sections_spec, start=1)
            ],
        )
        return _export_placeholder_report(document)

    def test_duplicate_paragraph_counts_into_gap_with_names(self) -> None:
        report = self._report(
            (
                ("sec_9_2", "9.2", _DUP_BODY + _UNIQUE_TAIL_A),
                ("sec_9_3", "9.3", _DUP_BODY + _UNIQUE_TAIL_B),
            )
        )
        reasons = " ".join(
            str(item.get("reason") or "") + str(item.get("section_heading") or "")
            for item in report.get("gap_sections") or []
        )
        self.assertIn("章节内容装配重复", reasons)
        self.assertIn("9.2", reasons)
        self.assertIn("9.3", reasons)
        self.assertGreaterEqual(int(report.get("gap_count") or 0), 1)

    def test_unique_document_not_gapped_by_duplication(self) -> None:
        report = self._report(
            (
                ("sec_9_2", "9.2", _DUP_BODY + _UNIQUE_TAIL_A),
                ("sec_9_3", "9.3", _DUP_BODY[:70] + _UNIQUE_TAIL_B),
            )
        )
        reasons = " ".join(
            str(item.get("reason") or "")
            for item in report.get("gap_sections") or []
        )
        self.assertNotIn("章节内容装配重复", reasons)


if __name__ == "__main__":
    unittest.main()
