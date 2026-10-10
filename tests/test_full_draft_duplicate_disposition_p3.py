"""新纪元第3轮修订：复测N1——全稿采纳重复门从一票否决改为逐节处置。

现场（复测N1/N3）：P0-A 重复门检测到三处跨节重复后整体拒绝采纳、无逐节
出路、报错直出内部节 ID。修后契约：
T1 无处置时维持 fail-safe 整体拒绝，但异常携带结构化重复对
   （节号+标题+共享片段长度，供采纳面板列出三选一；正文错误文案用人话
   节号——9.2/9.3——不裸奔内部 section_id）；
T2 处置表 duplicate_dispositions：'skip'（本节跳过采纳，维持占位）/
   'adopt_with_gap'（仍要采纳，计入装配重复缺口→导出层草案-N）二值；
   涉事节全部被处置且无遗漏 → 放行采纳，结果分别记
   skipped_duplicate_sections / assembly_duplicate_sections；
T3 处置表缺项（仍有涉事节未处置）→ 仍拒绝并列出未处置节号（人话）；
T4 非法处置值 → ValueError（422）。
'重生成'出路=既有重新生成通道（cancel+重新提交），不在 adopt 语义内。
"""
from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

_DUP_BODY = (
    "主要终点将采用CMH检验比较两组应答者的比例，检验水准取单侧0.025，"
    "并按中心分层进行敏感性分析；关键次要终点按预先设定的检验顺序逐级检验，"
    "以控制整体I类错误率，全部推断均基于全分析集开展。"
)
_TAILS = {
    "sec_9_2": "本节另载明数据录入与时点安排的特有约定A。",
    "sec_9_3": "本节另载明数据录入与时点安排的特有约定B。",
    "sec_9_4": "本节另载明数据录入与时点安排的特有约定C。",
}
_HEADINGS = {
    "sec_9_2": ("9.2", "统计分析数据集"),
    "sec_9_3": ("9.3", "统计分析方法"),
    "sec_9_4": ("9.4", "敏感性分析"),
}


def _artifact():
    source_id = "study_definition_fake"
    locator = "study_definition:sd_fake:revision:1"
    quote = "适应症：哮喘"
    sections = []
    targets = []
    for section_id in ("sec_9_2", "sec_9_3", "sec_9_4"):
        number, heading = _HEADINGS[section_id]
        sections.append(
            {
                "section_id": section_id,
                "section_number": number,
                "heading": heading,
                "content_status": "complete",
                "proposal_text": _DUP_BODY + _TAILS[section_id],
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
        "study_definition": {"id": "sd_fake", "revision": 1, "sha256": "a" * 64},
        "source_bindings": [{"source_id": source_id, "locator": locator}],
        "sections": sections,
        "target_sections": targets,
    }


def _adopt(artifact, dispositions=None):
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
    cleanup = getattr(_adopt, "_cleanups", None)
    full = MedicalWritingFullDraftService(
        service_resolver=lambda project_id: service,
        artifact_root=Path(tmp.name),
    )
    full.read_artifact = lambda project_id, job: artifact
    job = SimpleNamespace(job_id="job_dup_disposition")
    return full.adopt(
        "proj_full_draft_fake",
        job,
        duplicate_dispositions=dispositions,
    )


class DuplicateDispositionTests(unittest.TestCase):
    def test_no_disposition_raises_structured_pairs_with_human_numbers(self) -> None:
        from services.api.app.medical_writing_full_draft import (
            FullDraftDuplicateSectionsError,
        )

        with self.assertRaises(FullDraftDuplicateSectionsError) as refused:
            _adopt(_artifact())
        error = refused.exception
        self.assertTrue(error.duplicate_pairs)
        pair = error.duplicate_pairs[0]
        self.assertIn("sections", pair)
        self.assertIn("shared_fragment_chars", pair)
        named = {item["section_number"] for item in pair["sections"]}
        self.assertEqual({"9.2", "9.3", "9.4"}, named)
        self.assertIn("9.2", str(error))
        self.assertIn("9.3", str(error))

    def test_skip_dispositions_adopt_remaining_sections(self) -> None:
        result = _adopt(
            _artifact(),
            {"sec_9_3": "skip", "sec_9_4": "skip"},
        )
        self.assertIn("sec_9_2", result["adopted_section_ids"])
        self.assertEqual(["sec_9_3", "sec_9_4"], result["skipped_duplicate_sections"])

    def test_adopt_with_gap_records_duplicate_sections(self) -> None:
        result = _adopt(
            _artifact(),
            {
                "sec_9_2": "adopt_with_gap",
                "sec_9_3": "adopt_with_gap",
                "sec_9_4": "adopt_with_gap",
            },
        )
        self.assertEqual(3, result["adopted_count"])
        self.assertEqual(
            ["sec_9_2", "sec_9_3", "sec_9_4"],
            result["assembly_duplicate_sections"],
        )

    def test_partial_keep_with_undecided_member_still_refuses(self) -> None:
        # 三选一是逐节契约：涉事节未逐一表态即拒绝（采纳面板会列出全组）。
        from services.api.app.medical_writing_full_draft import (
            FullDraftDuplicateSectionsError,
        )

        with self.assertRaises(FullDraftDuplicateSectionsError) as refused:
            _adopt(_artifact(), {"sec_9_3": "adopt_with_gap", "sec_9_4": "adopt_with_gap"})
        self.assertIn("9.2", str(refused.exception))

    def test_partial_disposition_still_refuses_and_names_undecided(self) -> None:
        from services.api.app.medical_writing_full_draft import (
            FullDraftDuplicateSectionsError,
        )

        with self.assertRaises(FullDraftDuplicateSectionsError) as refused:
            _adopt(_artifact(), {"sec_9_3": "skip"})
        message = str(refused.exception)
        self.assertIn("未处置", message)
        self.assertIn("9.4", message)

    def test_invalid_disposition_value_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            _adopt(_artifact(), {"sec_9_3": "whatever"})


if __name__ == "__main__":
    unittest.main()
