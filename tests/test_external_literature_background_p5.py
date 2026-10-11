"""P0-2 背景外查三件套（owner 裁定 20261001 + 两次补充）六条反例 + 文献
链路体检（T7-T12 并入）。

反例契约：
R1 背景类章节缺流行病学/指南/治疗现状来源且外查 hit → 不得作为 source_gap
   阻断：降级解除（partial）+ PMID 留痕（候选绑定）；
R2 外查 failed（网络失败/空结果）→ 诚实降级：维持 source_gap 并留痕；
R3 研究药物自身数据边界不变：缺 IB/研究药物资料类来源时即使外查 hit 也
   维持 source_gap；
R4 PMID 不可回验拒绝：非数字 PMID 剔除；efetch 响应缺请求 PMID 时记
   missing，不落入档案库；
R5 角标与文末列表纯代码渲染：双格式（Vancouver 默认/GB-T 7714 可选）同一
   输入两次渲染逐字一致；期刊缩写用 NLM TA、缺失保留全称；模型自写的
   文末式引文行被检出（禁止模型写引文文本）；
R6 知网 cnki_not_integrated 不做硬集成：require_source_integrated('cnki')
   显式拒绝。

体检五项映射：PMID 解析（R4）、元数据落库（archive roundtrip）、候选绑定
（R1 的 PMID 留痕）、角标渲染（R5）、双格式确定性（R5）。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from services.api.app.medical_writing_external_literature import (
    ExternalLiteratureArchive,
    ExternalLiteratureNotIntegratedError,
    ExternalLiteratureRecord,
    PubMedEUtilsClient,
    apply_background_external_lookup,
    attach_citation_markers,
    background_gap_classes_overridable,
    external_lookup_outcome,
    format_reference_gbt7714,
    format_reference_vancouver,
    model_authored_bibliography_lines,
    parse_pubmed_efetch_xml,
    pmid_is_wellformed,
    require_source_integrated,
    render_reference_list,
    source_integration_status,
)

_EFETCH_XML = """<?xml version="1.0"?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>31493397</PMID>
      <Article>
        <Journal>
          <Title>Gastroenterology</Title>
          <ISOAbbreviation>Gastroenterology</ISOAbbreviation>
          <JournalIssue><PubDate><Year>2019</Year></PubDate></JournalIssue>
        </Journal>
        <ArticleTitle>Mirikizumab for ulcerative colitis: a phase 2 study.</ArticleTitle>
        <AuthorList><Author><LastName>Sands</LastName><Initials>BE</Initials></Author></AuthorList>
      </Article>
    </MedlineCitation>
  </PubmedArticle>
</PubmedArticleSet>
"""

_RECORD = ExternalLiteratureRecord(
    pmid="31493397",
    title="Mirikizumab for ulcerative colitis: a phase 2 study.",
    journal="Gastroenterology",
    journal_ta="Gastroenterology",
    pub_year="2019",
    authors=("Sands BE",),
    doi="10.1053/j.gastro.2019.03.047",
)


def _background_section(missing):
    return {
        "section_id": "sec_1_1",
        "section_number": "1.1",
        "heading": "疾病背景及治疗现状",
        "content_status": "source_gap",
        "proposal_text": "",
        "missing_source_classes": missing,
    }


class PmidParsingTests(unittest.TestCase):
    def test_malformed_pmids_are_rejected_everywhere(self) -> None:
        """R4a：非数字/零开头 PMID 一律不合法。"""
        for bad in ("", "abc", "0", "0123", "12a45", "1234567890"):
            self.assertFalse(pmid_is_wellformed(bad), bad)
        self.assertTrue(pmid_is_wellformed("31493397"))

    def test_efetch_missing_pmid_reported_not_silently_accepted(self) -> None:
        """R4b：efetch 响应缺请求 PMID → 记 missing，不伪造记录。"""
        client = PubMedEUtilsClient(
            archive_dir=Path(tempfile.mkdtemp()),
            fetch_text=lambda url: _EFETCH_XML,
        )
        outcome = client.fetch_records(["31493397", "99999999"])
        self.assertIn("99999999", outcome["missing_pmids"])
        self.assertIn("31493397", outcome["records"])


class ArchiveRoundtripTests(unittest.TestCase):
    def test_metadata_persisted_with_raw_paths_and_readable(self) -> None:
        """体检·元数据落库：PMID 唯一、原文留档路径随记录、可读回。"""
        with tempfile.TemporaryDirectory() as tmp:
            archive = ExternalLiteratureArchive(Path(tmp) / "lit.sqlite3")
            written = archive.upsert_records(
                {"31493397": _RECORD},
                raw_esearch_path="/tmp/esearch_x.json",
                raw_efetch_path="/tmp/efetch_x.xml",
            )
            self.assertEqual(1, written)
            record = archive.get("31493397")
            self.assertIsNotNone(record)
            self.assertEqual("Gastroenterology", record.journal)
            self.assertEqual(("Sands BE",), record.authors)
            # 原文留档真实存在（检索原文留档契约）
            for kind in ("esearch", "efetch"):
                client_archive = PubMedEUtilsClient(
                    archive_dir=Path(tmp),
                    fetch_json=lambda url: {"esearchresult": {"idlist": ["31493397"]}},
                    fetch_text=lambda url: _EFETCH_XML,
                )
                outcome = client_archive.search("ulcerative colitis mirikizumab")
                self.assertTrue(Path(outcome["raw_archive_path"]).exists())
                client_archive.fetch_records(["31493397"])
                break


class BackgroundLookupRuleTests(unittest.TestCase):
    def test_r1_background_gap_downgraded_when_lookup_hits(self) -> None:
        missing = ["epidemiology", "guidelines", "treatment_landscape"]
        self.assertTrue(background_gap_classes_overridable(missing))
        section = _background_section(missing)
        apply_background_external_lookup(
            section,
            external_lookup_outcome(
                status="hit",
                records=[_RECORD],
                note="PubMed 命中",
            ),
        )
        self.assertEqual("partial", section["content_status"])
        self.assertEqual("hit", section["background_external_lookup"]["status"])
        self.assertIn("31493397", section["proposal_text"])
        # 候选绑定：PMID 与题名留痕在工件内
        self.assertEqual("Mirikizumab for ulcerative colitis: a phase 2 study.",
                         section["background_external_lookup"]["records"][0]["title"])

    def test_r2_failed_lookup_keeps_source_gap(self) -> None:
        missing = ["epidemiology", "guidelines"]
        for status, note in (("failed", "网络失败"), ("not_attempted", "未配置外查")):
            section = _background_section(missing)
            apply_background_external_lookup(
                section, external_lookup_outcome(status=status, note=note)
            )
            self.assertEqual("source_gap", section["content_status"])
            self.assertEqual(status, section["background_external_lookup"]["status"])

    def test_r3_drug_specific_missing_never_overridden(self) -> None:
        for missing in (["ib"], ["investigational_product", "epidemiology"], ["prior_clinical"]):
            self.assertFalse(
                background_gap_classes_overridable(missing),
                f"药物特异缺失不得被外查覆盖：{missing}",
            )
            section = _background_section(missing)
            apply_background_external_lookup(
                section, external_lookup_outcome(status="hit", records=[_RECORD])
            )
            self.assertEqual("source_gap", section["content_status"])

    def test_non_background_section_untouched(self) -> None:
        section = _background_section(["epidemiology"])
        section["heading"] = "统计学考虑"
        apply_background_external_lookup(
            section, external_lookup_outcome(status="hit", records=[_RECORD])
        )
        self.assertEqual("source_gap", section["content_status"])


class CitationRenderingTests(unittest.TestCase):
    def test_r5_both_formats_deterministic_and_marker_pure_code(self) -> None:
        """R5：双格式确定性 + 角标纯代码。"""
        v1 = render_reference_list([_RECORD], "vancouver")
        v2 = render_reference_list([_RECORD], "vancouver")
        g1 = render_reference_list([_RECORD], "gbt_7714_2015_numeric")
        g2 = render_reference_list([_RECORD], "gbt_7714_2015_numeric")
        self.assertEqual(v1, v2)
        self.assertEqual(g1, g2)
        self.assertNotEqual(v1, g1)
        self.assertTrue(v1[0].startswith("[1] "))
        self.assertIn("Gastroenterology", v1[0])
        self.assertIn("DOI:", g1[0])
        marked = attach_citation_markers("疾病负担显著。", ["31493397"])
        self.assertIn("[1]", marked)
        self.assertEqual(
            "疾病负担显著。（外部文献核查：[1]）", marked,
        )

    def test_r5_journal_abbreviation_uses_ta_else_full_title(self) -> None:
        with_ta = format_reference_vancouver(1, _RECORD)
        self.assertIn("Gastroenterology", with_ta)
        no_ta = ExternalLiteratureRecord(
            pmid="12345678",
            title="另一篇标题足够长以通过体检。",
            journal="中华流行病学杂志",
            journal_ta="",
            pub_year="2021",
            authors=("张三",),
            doi="",
        )
        rendered = format_reference_gbt7714(1, no_ta)
        self.assertIn("中华流行病学杂志", rendered)

    def test_r5_model_authored_bibliography_lines_detected(self) -> None:
        body = (
            "疾病背景正文一句。\n"
            "[1] Sands BE. Mirikizumab for ulcerative colitis. Gastroenterology. 2019.\n"
            "结尾正常句。"
        )
        hits = model_authored_bibliography_lines(body)
        self.assertEqual(1, len(hits))
        self.assertTrue(hits[0].startswith("[1]"))

    def test_unknown_style_rejected(self) -> None:
        from services.api.app.medical_writing_external_literature import (
            ExternalLiteratureError,
        )

        with self.assertRaises(ExternalLiteratureError):
            render_reference_list([_RECORD], "ama")


class CnkiBoundaryTests(unittest.TestCase):
    def test_r6_cnki_marked_not_integrated_and_refused(self) -> None:
        """R6：知网 cnki_not_integrated，不做硬集成。"""
        self.assertEqual("cnki_not_integrated", source_integration_status("cnki"))
        self.assertEqual("integrated", source_integration_status("pubmed"))
        with self.assertRaises(ExternalLiteratureNotIntegratedError):
            require_source_integrated("cnki")
        require_source_integrated("pubmed")  # 不抛

    def test_unknown_source_rejected(self) -> None:
        from services.api.app.medical_writing_external_literature import (
            ExternalLiteratureError,
        )

        with self.assertRaises(ExternalLiteratureError):
            source_integration_status("wanfang")

    def test_efetch_xml_parser_offline_roundtrip(self) -> None:
        records = parse_pubmed_efetch_xml(_EFETCH_XML)
        self.assertIn("31493397", records)
        self.assertEqual("2019", records["31493397"].pub_year)
        self.assertEqual("Sands BE", records["31493397"].authors[0])


if __name__ == "__main__":
    unittest.main()
