"""新纪元第2轮末修订（P0-2/N1门仲裁）：守卫刻意标记节放行——空内容门
不再对守卫工作产物一票否决。

现场（retest_r1 v2§2.2 实测形态）：剂量/统计装配/样本量守卫刻意写入
【…待确认…】标记（6.5/7.1.4/9/9.5 四节），空内容门的占位正则命中
'待确认' → 批量采纳恒 409、重生成确定性再标记、无出路——上一轮的
CAS 重锚修复因此浏览器不可达（单测绿）。

修后契约（反例先红）：
T1 含 4 个守卫标记节（剂量待确认/统计章分节装配待确认/样本量口径混写
   待确认/样本量待确认）的工件批量采纳必须成功——标记是守卫工作产物，
   缺口语义由导出层缺口门接管（草案-N）；
T2 真占位（'待补充'，非守卫标记）仍被拒（守卫放行不放松占位门）；
T3 拒绝文案用节号（9.2）不裸奔内部 section_id（r1-N3 族人话化）。
"""
from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

_DOPING = (
    "本节另载明与试验药物给药安排相关的本项目特有执行细节，供医学经理"
    "逐句审阅后写入工作副本；下列守卫标记为生成层工作产物。"
)

_GUARD_MARKERS = {
    "sec_6_5": "【剂量待确认：本节未载明研究药物的剂量与规格（无 mg/毫克/IU 等剂量单位）；需IB/立项补剂量方案后写入，正式稿不得带此标记。】",
    "sec_9_1": "【样本量口径混写待确认：本节同时出现『单侧』与『双侧』的检验设定表述——同一α/把握度组合只能有一个口径（两套z值差可达22%例数）；锁定条件：统一口径并按统一口径重算样本量后解除，正式稿不得带此标记。】",
    "sec_9_2": "【统计章分节装配待确认：本统计章缺少：非盲统计师防火墙（对齐成型方案统计章结构：分析集成员规则/多重性终点族/敏感性双法/顺序检验声明/非盲统计师防火墙）；锁定条件：按已确认设计事实逐件补齐后解除，未声明处不得编造（如检验树），正式稿不得带此标记。】",
    "sec_9_5": "【样本量待确认：当前声明每组45例，但样本量假设要素不全（缺组间差/SD/α/把握度），系统无法复算；锁定条件：补齐假设并使复算与声明一致（差值≤±20%）后解除，正式稿不得带此标记。】",
}
_HEADINGS = {
    "sec_6_5": ("6.5", "给药调整"),
    "sec_9_1": ("9.1", "样本量"),
    "sec_9_2": ("9.2", "统计分析数据集"),
    "sec_9_5": ("9.5", "安全性分析集"),
}


def _artifact(marker_for: dict[str, str] | None = None):
    # 未点名的节保留默认守卫标记（覆盖式 override 只改指定节）
    merged = {sid: _GUARD_MARKERS[sid] for sid in _GUARD_MARKERS}
    merged.update(marker_for or {})
    marker_for = merged
    source_id = "study_definition_fake"
    locator = "study_definition:sd_fake:revision:1"
    quote = "适应症：哮喘"
    sections = []
    targets = []
    for section_id in _GUARD_MARKERS:
        number, heading = _HEADINGS[section_id]
        proposal = _DOPING + marker_for.get(section_id, "")
        sections.append(
            {
                "section_id": section_id,
                "section_number": number,
                "heading": heading,
                "content_status": "complete",
                "proposal_text": proposal,
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


def _adopt(artifact):
    from services.api.app.medical_writing_full_draft import (
        MedicalWritingFullDraftService,
    )
    from tests.test_medical_writing_full_draft import _FakeRepo

    repo = _FakeRepo()
    for section in artifact["target_sections"]:
        repo.working[section["section_id"]] = SimpleNamespace(
            revision=0,
            content_blocks=[
                {"block_id": section["body_block_id"], "block_type": "paragraph", "text": ""}
            ],
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
    full = MedicalWritingFullDraftService(
        service_resolver=lambda project_id: service,
        artifact_root=Path(tmp.name),
    )
    full.read_artifact = lambda project_id, job: artifact
    job = SimpleNamespace(job_id="job_guard_marker_adopt")
    return full.adopt("proj_full_draft_fake", job), repo


class GuardMarkerAdoptionTests(unittest.TestCase):
    def test_guard_marked_sections_batch_adopt(self) -> None:
        """T1：四守卫标记节的工件批量采纳必须成功（N1 现场形态）。"""
        result, repo = _adopt(_artifact())
        self.assertEqual(4, result["adopted_count"])
        self.assertEqual(
            {"sec_6_5", "sec_9_1", "sec_9_2", "sec_9_5"},
            set(result["adopted_section_ids"]),
        )
        # 标记随正文写入工作副本（导出层缺口门据此计草案-N）
        self.assertIn(
            "【剂量待确认", repo.working["sec_6_5"].content_blocks[-1]["text"]
        )

    def test_real_placeholder_still_rejected(self) -> None:
        """T2：真占位（'待补充'）不因守卫放行而松门。"""
        artifact = _artifact(marker_for={"sec_9_2": "本章其余内容待补充。"})
        from services.api.app.medical_writing_full_draft import RuntimeStoreError

        with self.assertRaises(RuntimeStoreError) as refused:
            _adopt(artifact)
        # T3：文案人话化——节号上屏，内部 section_id 不裸奔
        self.assertIn("9.2", str(refused.exception))
        self.assertNotIn("sec_9_2", str(refused.exception))


if __name__ == "__main__":
    unittest.main()
