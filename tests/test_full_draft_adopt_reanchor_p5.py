"""新纪元第1轮末修订（P0-1）：N1″采纳 CAS 重锚——主线采纳链断根治。

现场（R4 复盘 N1″）：adopt 的目标表（target_sections）在工件构建时快照
expected_revision/body_sha256；采纳循环对未写节做『live revision==快照』
硬门。快照后任何节修订号跟涨（如初版工作副本保存晚于目标表构建），首个
未写节恒定报『全文初稿采纳遇到章节版本变化』，整批采纳死路（已写节文本
相等回放先于版本门，故前几节回放后第 5 节必撞门）。

修后契约（反例先红）：
T1 快照版本落后（目标表构建后某节 revision+1、正文仍空）：目标表仅作
   正文差异基线——采纳必须完成，该节照写，回放/采纳计数正确；
T2 快照后正文已被改成 proposal 本身（文本相等）：自动回放，不重复写、
   不报版本变化；
T3 save CAS 冲突重锚续跑：并发写把 revision 顶掉导致 save 抛
   StaleRuntimeStateError 时，按 live 状态重锚（重读 working_copy、以
   刚读 revision 重新 CAS）续跑而非中断整批；重锚次数有界，仍失败才上抛。
"""
from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from services.api.app.medical_writing_repository import StaleRuntimeStateError

_PROPOSAL_A = (
    "本节载明研究背景与立题依据：按已确认适应症与分期陈述疾病现状、现有"
    "治疗格局与未满足需求，说明本研究的立题理由，并在正文中保持与来源证据"
    "一一对应的连续监管中文表述，供医学经理逐句审阅与采纳确认。"
)
_PROPOSAL_B = (
    "本节载明研究目的与终点分层：主要终点给出定义、评价时点、归因口径与"
    "统计推断方式，关键次要终点按检验顺序逐级陈述，探索性终点单独列示；"
    "全部终点与研究目的保持一一对应，供医学审阅与后续统计章衔接。"
)


def _artifact(target_revisions: dict[str, int] | None = None):
    source_id = "study_definition_fake"
    locator = "study_definition:sd_fake:revision:1"
    quote = "适应症：哮喘"
    proposals = {"sec_1": _PROPOSAL_A, "sec_2": _PROPOSAL_B}
    sections = []
    targets = []
    for section_id in ("sec_1", "sec_2"):
        proposals[section_id] = proposals[section_id]
        sections.append(
            {
                "section_id": section_id,
                "section_number": "1" if section_id == "sec_1" else "2",
                "heading": "研究背景" if section_id == "sec_1" else "研究目的",
                "content_status": "complete",
                "proposal_text": proposals[section_id],
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
                "body_block_id": f"b_{section_id[-1]}",
                "expected_revision": (target_revisions or {}).get(section_id, 0),
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


def _adopt(artifact, *, repo_patch=None):
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
    if repo_patch is not None:
        repo_patch(repo)
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
    job = SimpleNamespace(job_id="job_adopt_reanchor_p5")
    return full.adopt("proj_full_draft_fake", job), repo


class AdoptReanchorTests(unittest.TestCase):
    def test_stale_snapshot_revision_no_longer_aborts_batch(self) -> None:
        """T1：目标表构建后某节 revision+1（快照 stale）——采纳照常完成。"""
        artifact = _artifact(target_revisions={"sec_2": 5})
        # 模拟快照后保存初版工作副本：live revision=1，快照却写 0/5 均不等
        result, repo = _adopt(artifact, repo_patch=lambda repo: (
            repo.working["sec_1"].__setattr__("revision", 1),
            repo.working["sec_2"].__setattr__("revision", 1),
        ) and None)
        self.assertEqual(["sec_1", "sec_2"], result["adopted_section_ids"])
        self.assertEqual(2, result["adopted_count"])
        self.assertEqual([], result["replayed_section_ids"])
        # 两节正文均为 proposal（目标表只当差异基线，不拦版本）
        self.assertEqual(_PROPOSAL_A, repo.working["sec_1"].content_blocks[-1]["text"])
        self.assertEqual(_PROPOSAL_B, repo.working["sec_2"].content_blocks[-1]["text"])

    def test_text_equal_replays_even_when_snapshot_stale(self) -> None:
        """T2：快照后正文已被写成 proposal 本身——文本相等自动回放。"""
        artifact = _artifact(target_revisions={"sec_2": 3})
        def patch(repo):
            repo.working["sec_1"].revision = 2
            repo.working["sec_1"].content_blocks[-1]["text"] = _PROPOSAL_A
        result, repo = _adopt(artifact, repo_patch=patch)
        self.assertIn("sec_1", result["replayed_section_ids"])
        self.assertNotIn("sec_1", result["adopted_section_ids"])
        self.assertEqual(["sec_2"], result["adopted_section_ids"])
        self.assertEqual(1, result["adopted_count"])
        self.assertEqual(1, result["replayed_count"])
        # 回放节未被重写（revision 保持 2）
        self.assertEqual(2, repo.working["sec_1"].revision)

    def test_cas_conflict_reanchors_and_finishes_batch(self) -> None:
        """T3：save CAS 冲突（并发写顶掉 revision）→ 重锚续跑不弃批。"""
        artifact = _artifact()
        calls = {"sec_1": 0}

        def patch(repo):
            original = repo.save_working_copy

            def flaky(project_id, section_id, request):
                if section_id == "sec_1":
                    calls["sec_1"] += 1
                    if calls["sec_1"] == 1:
                        # 并发写：读后被人顶掉一个版本 → 首次 CAS 抛 stale
                        repo.working[section_id].revision += 1
                        raise StaleRuntimeStateError("stale fake working copy")
                return original(project_id, section_id, request)

            repo.save_working_copy = flaky

        result, repo = _adopt(artifact, repo_patch=patch)
        self.assertEqual(["sec_1", "sec_2"], result["adopted_section_ids"])
        self.assertEqual(2, result["adopted_count"])
        # 重锚后续写以重读 revision 为锚：sec_1 最终 revision=2（并发+1 与
        # 采纳+1），正文为 proposal。
        self.assertEqual(2, repo.working["sec_1"].revision)
        self.assertEqual(_PROPOSAL_A, repo.working["sec_1"].content_blocks[-1]["text"])
        self.assertEqual(calls["sec_1"], 2)


if __name__ == "__main__":
    unittest.main()
