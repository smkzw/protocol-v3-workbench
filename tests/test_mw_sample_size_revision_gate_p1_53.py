"""新纪元第1轮修订（E9）：P1-53 样本量修订路径三件套——口径指纹、
强制重算、单双侧混写禁令（规格：t17_round27_loop/
SPEC_sample_size_revision_gate_P1-53.md）。

现场（AD 基准轮，r11 聚合侧复算独立验证）：结构化输入保存
『单侧把握度90%+850例（567/283）』的陈旧推导——假设从 28%vs18% 修订为
38%vs18% 后基数未重算，850 在 2:1 下把握度≈100%，陈旧基数一路走到
导出件；且声明段按双侧混写。P0-18（18ed698b）输入层门只覆盖
『新输入的 z 向量绑定』时点校验，未覆盖『假设修订后基数不重算』路径。

红用例（先红后修）：
T1 口径指纹 sample_size_fingerprint：五要素（单双侧|α|把握度|δ|SD，
比例型由 p1/p2 推导 δ/SD）齐才产 16 位指纹；假设修订（28%→38%）指纹
必变；要素缺失返回 None；
T2 修订复算门 sample_size_revision_check：AD 修订文本（850 未重算）判
『不一致』并给出复算明细；重算后文本（237/158/79）判『自洽』；
ID701（96/113/230）与比例正例（51/102/192）不误伤；
T3 commit_stage 修订强制重算：首存 AD 原始推导放行且指纹随 PICOS 持久
化；假设修订后不重算 → 完成第二步被 422（ValueError，人话明细）拦截；
重算通过后提交成功，新旧指纹与复算结果入 journey 事件留痕；
T4 单双侧混写：生成层给混写统计章加悬置块（含锁定条件）；导出层把
混写计入缺口（草案-N 强制）。『双单侧』（TOST）与『双侧可信区间』
不算混写。
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

AD_ORIGINAL = (
    "样本量按两比例之差计算：基于外部锚点预期应答率28%与对照18%，"
    "单侧α=0.05、把握度90%，共850例（567/283）。"
)
AD_REVISED = (
    "样本量按两比例之差计算：基于外部锚点预期应答率38%与对照18%，"
    "单侧α=0.05、把握度90%，共850例（567/283）。"
)
AD_RECOMPUTED = (
    "样本量按两比例之差计算：基于外部锚点预期应答率38%与对照18%，"
    "单侧α=0.05、把握度90%，共237例（158/79）。"
)
ID701_TEXT = (
    "按组间差1.5、SD 3.2、双侧α=0.05、把握度90%，复算需每组96例；"
    "考虑15%脱落放大后每组113例，共230例。"
)
POSITIVE_PROPORTION_TEXT = (
    "本研究按两比例之差的检验计算样本量：基于外部锚点预期应答率47.4%与"
    "对照22.5%，单侧α=0.025、把握度80%，需51例/组（两个队列共102例，"
    "考虑脱落扩展至192例）。"
)


def _fp(text: str):
    from services.api.app.medical_writing_full_draft import (
        sample_size_fingerprint,
    )

    return sample_size_fingerprint(text)


def _revision_check(text: str):
    from services.api.app.medical_writing_full_draft import (
        sample_size_revision_check,
    )

    return sample_size_revision_check(text)


class FingerprintTests(unittest.TestCase):
    def test_five_elements_present_yields_16_hex_fingerprint(self) -> None:
        fingerprint = _fp(AD_ORIGINAL)
        self.assertIsNotNone(fingerprint)
        self.assertEqual(16, len(fingerprint))
        int(fingerprint, 16)  # 16 位十六进制

    def test_assumption_revision_changes_fingerprint(self) -> None:
        self.assertNotEqual(_fp(AD_ORIGINAL), _fp(AD_REVISED))

    def test_missing_elements_yield_none(self) -> None:
        self.assertIsNone(_fp("本研究为随机双盲安慰剂对照研究。"))
        self.assertIsNone(
            _fp("基于外部锚点预期应答率38%与对照18%，共850例（567/283）。")
        )

    def test_continuous_craft_also_fingerprints(self) -> None:
        self.assertIsNotNone(_fp(ID701_TEXT))


class RevisionCheckTests(unittest.TestCase):
    def test_ad_stale_total_is_inconsistent_with_detail(self) -> None:
        check = _revision_check(AD_REVISED)
        self.assertIsNotNone(check)
        self.assertEqual("不一致", check["status"])
        self.assertEqual(283, check["declared_per_group"])
        self.assertTrue(check["required_per_group"] < 150)
        self.assertIn("重算", check["detail"])

    def test_ad_recomputed_form_is_consistent(self) -> None:
        check = _revision_check(AD_RECOMPUTED)
        self.assertIsNotNone(check)
        self.assertEqual("自洽", check["status"])

    def test_id701_positive_not_harmed(self) -> None:
        check = _revision_check(ID701_TEXT)
        self.assertNotEqual("不一致", (check or {}).get("status"))

    def test_positive_proportion_craft_not_harmed(self) -> None:
        check = _revision_check(POSITIVE_PROPORTION_TEXT)
        self.assertNotEqual("不一致", (check or {}).get("status"))

    def test_plain_text_returns_none(self) -> None:
        self.assertIsNone(_revision_check("本研究为随机双盲安慰剂对照研究。"))


class CommitStageRevisionGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        from services.api.app.medical_writing_authoring_journey import (
            MedicalWritingAuthoringJourneyService,
        )
        from packages.contracts.workbench_contracts import (
            MedicalWritingAuthoringJourneyCreateRequest,
        )
        from tests.test_medical_writing_authoring_journey import (
            _complete_framing,
            _complete_picos,
        )

        self._complete_picos = _complete_picos
        self.db_path = Path(self.tmp.name) / "journeys.sqlite3"
        self.service = MedicalWritingAuthoringJourneyService(self.db_path)
        self.project_id = "proj_sample_size_revision_p1_53"
        framed = self.service.create(
            self.project_id,
            MedicalWritingAuthoringJourneyCreateRequest(
                framing=_complete_framing(),
                actor="medical_manager_test",
                idempotency_key="create-ss-rev-p1-53",
            ),
        )
        self.base_revision = framed.revision

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _commit_picos(self, strategy: str, key: str, expected_revision: int | None = None):
        from packages.contracts.workbench_contracts import (
            MedicalWritingAuthoringJourneyCommitRequest,
            MedicalWritingJourneyImpactPreviewRequest,
        )

        revision = (
            expected_revision
            if expected_revision is not None
            else self.base_revision
        )
        picos = self._complete_picos()
        picos.sample_size_strategy = strategy
        preview = self.service.impact_preview(
            self.project_id,
            MedicalWritingJourneyImpactPreviewRequest(
                expected_revision=revision,
                stage="picos",
                picos=picos,
            ),
        )
        return self.service.commit_stage(
            self.project_id,
            MedicalWritingAuthoringJourneyCommitRequest(
                expected_revision=revision,
                stage="picos",
                picos=picos,
                impact_preview_id=preview.preview_id,
                actor="medical_manager_test",
                idempotency_key=key,
            ),
        )

    def test_first_commit_persists_fingerprint(self) -> None:
        committed = self._commit_picos(AD_ORIGINAL, "commit-ss-rev-first-p1-53")
        self.assertTrue(committed.picos_complete)
        self.assertEqual(_fp(AD_ORIGINAL), committed.picos.sample_size_fingerprint)

    def test_revision_without_recompute_is_blocked(self) -> None:
        first = self._commit_picos(AD_ORIGINAL, "commit-ss-rev-first-block-p1-53")
        with self.assertRaises(ValueError) as refused:
            self._commit_picos(
                AD_REVISED,
                "commit-ss-rev-stale-p1-53",
                expected_revision=first.revision,
            )
        message = str(refused.exception)
        self.assertIn("假设已修订", message)
        self.assertIn("重算", message)

    def test_recomputed_revision_commits_with_event_trail(self) -> None:
        first = self._commit_picos(AD_ORIGINAL, "commit-ss-rev-first-trail-p1-53")
        second = self._commit_picos(
            AD_RECOMPUTED,
            "commit-ss-rev-recomputed-p1-53",
            expected_revision=first.revision,
        )
        self.assertTrue(second.picos_complete)
        self.assertEqual(
            _fp(AD_RECOMPUTED), second.picos.sample_size_fingerprint
        )
        connection = sqlite3.connect(self.db_path)
        try:
            rows = connection.execute(
                "SELECT payload_json FROM"
                " medical_writing_authoring_journey_events"
                " WHERE project_id = ? AND event_type LIKE '%picos_committed'"
                " ORDER BY created_at",
                (self.project_id,),
            ).fetchall()
        finally:
            connection.close()
        self.assertTrue(rows)
        trail_found = False
        for (payload,) in rows:
            detail = json.loads(payload)
            blob = json.dumps(detail, ensure_ascii=False)
            if "sample_size_revision" in blob:
                trail_found = True
                self.assertIn("old_fingerprint", blob)
                self.assertIn("new_fingerprint", blob)
                self.assertNotEqual(
                    detail["sample_size_revision"]["old_fingerprint"],
                    detail["sample_size_revision"]["new_fingerprint"],
                )
        self.assertTrue(
            trail_found,
            "假设修订的提交事件必须留痕新旧指纹与复算结果（供审阅侧看到基数因何变化）。",
        )


class SidednessMixingTests(unittest.TestCase):
    MIXED_SECTION = {
        "section_number": "9.1",
        "heading": "样本量与检验假设",
        "proposal_text": (
            "样本量计算采用双侧α=0.05、把握度90%的假设；推导过程按单侧"
            "α=0.05 计算检验把握度，需每组82例。"
        ),
    }
    TOST_SECTION = {
        "section_number": "9.1",
        "heading": "样本量与检验假设",
        "proposal_text": (
            "等效性检验采用双单侧α=0.05、把握度80%，需每组120例；"
            "总体成功率以双侧95%可信区间估计。"
        ),
    }

    def _mixing(self, text: str) -> bool:
        from services.api.app.medical_writing_full_draft import (
            sample_size_sidedness_mixing_check,
        )

        return sample_size_sidedness_mixing_check(text)

    def test_detector_flags_declaration_mixing(self) -> None:
        self.assertTrue(self._mixing(self.MIXED_SECTION["proposal_text"]))

    def test_detector_allows_tost_and_ci_wording(self) -> None:
        self.assertFalse(self._mixing(self.TOST_SECTION["proposal_text"]))
        self.assertFalse(self._mixing(AD_ORIGINAL))

    def test_generation_guard_adds_suspension_block(self) -> None:
        from services.api.app.medical_writing_full_draft import (
            apply_sample_size_guard_to_section,
        )

        section = dict(self.MIXED_SECTION)
        original = section["proposal_text"]
        apply_sample_size_guard_to_section(section, anchor="")
        self.assertIn("口径混写", section["proposal_text"])
        self.assertIn("锁定条件", section["proposal_text"])
        self.assertIn(original[:10], section["proposal_text"])

    def test_export_gate_counts_mixing_into_gap(self) -> None:
        from services.api.app.main import _export_placeholder_report
        from packages.contracts.workbench_contracts import (
            ProtocolDocument,
            ProtocolSection,
        )

        document = ProtocolDocument(
            document_id="doc_ss_mixing",
            project_id="proj_ss_mixing",
            protocol_id="CMS-SS-MIX",
            version="1.0",
            sections=[
                ProtocolSection(
                    section_id="sec_9",
                    document_id="doc_ss_mixing",
                    heading="统计学",
                    section_number="9",
                    content_blocks=[
                        {
                            "block_id": "b9",
                            "block_type": "paragraph",
                            "text": self.MIXED_SECTION["proposal_text"],
                        }
                    ],
                )
            ],
        )
        report = _export_placeholder_report(document)
        reasons = " ".join(
            str(item.get("reason") or "")
            + str(item.get("section_heading") or "")
            for item in report.get("gap_sections") or []
        )
        self.assertIn("口径混写", reasons)
        self.assertGreaterEqual(int(report.get("gap_count") or 0), 1)


if __name__ == "__main__":
    unittest.main()
