from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from services.api.app.eligibility_protocol_rules import (
    ELIGIBILITY_PROTOCOL_MANIFEST_ENV,
    EligibilityProtocolProjectConfig,
    EligibilityProtocolRule,
    EligibilityProtocolRuleService,
    _find_canonical_section_headings,
    _source_number_identity,
)
from services.api.app.protocol_text_extractor import (
    ProtocolParagraph,
    ProtocolTextDocument,
    parse_protocol_docx,
)


D001_PROTOCOL = Path(
    "/Users/smkzw/Documents/康哲项目资料/AI/入排/test-D001项目/"
    "CMS-D001 银屑病2、3期临床方案 v1.0-2025.12.21.docx"
)
MY009_PROTOCOL = Path(
    "/Users/smkzw/Documents/朗来项目资料/MY009治疗UC/方案及配套资料/3.0/"
    "MY009-UC-Ⅱa期-临床研究方案-V3.0 20250926-clean (1).docx"
)
RUX_PROTOCOL = Path(
    "/Users/smkzw/Documents/康哲项目资料/Ruxolitinib-AD/CFDI Inspection/"
    "RUX-03-002-自查文件包-20260107/10-临床试验重要文件/1-临床试验方案/"
    "V1.3版-2024.8.14/磷酸芦可替尼乳膏-AD3期临床研究方案V1.3-clean-20240814.docx"
)
TEST_PROTOCOL_CONFIGS = (
    EligibilityProtocolProjectConfig(
        project_id="proj_rux_03_002",
        aliases=("rux_03_002_monitoring_raw", "rux-03-002"),
        protocol_path=RUX_PROTOCOL,
        source_entry="rux_03_002_protocol_v1_3",
        source_version="V1.3 / 2024-08-14",
    ),
    EligibilityProtocolProjectConfig(
        project_id="proj_d001",
        aliases=("d001_raw_intake", "proj_d001_raw_intake", "cms-d001"),
        protocol_path=D001_PROTOCOL,
        source_entry="d001_protocol_v1_0",
        source_version="V1.0 / 2025-12-21",
    ),
    EligibilityProtocolProjectConfig(
        project_id="proj_my009_uc",
        aliases=(
            "my009_uc",
            "my009_uc_raw_intake",
            "my009_uc_monitoring_raw",
        ),
        protocol_path=MY009_PROTOCOL,
        source_entry="my009_protocol_v3_0",
        source_version="V3.0 / 2025-09-26",
    ),
)


def _walk(rules: tuple[EligibilityProtocolRule, ...]):
    for rule in rules:
        yield rule
        yield from _walk(rule.children)


@unittest.skipUnless(
    D001_PROTOCOL.exists() and MY009_PROTOCOL.exists(),
    "D001 and MY009 raw protocols are required",
)
class EligibilityProtocolRuleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.service = EligibilityProtocolRuleService(TEST_PROTOCOL_CONFIGS)
        cls.d001 = cls.service.rules_for_project("d001_raw_intake")
        cls.my009 = cls.service.rules_for_project("my009_uc_raw_intake")

    def test_unconfigured_service_fails_closed_without_embedded_projects(self) -> None:
        with patch.dict(
            "os.environ",
            {ELIGIBILITY_PROTOCOL_MANIFEST_ENV: ""},
        ):
            service = EligibilityProtocolRuleService()
        with self.assertRaisesRegex(KeyError, "not configured"):
            service.rules_for_project("proj_d001")

    def test_external_source_manifest_injects_project_protocol(self) -> None:
        with TemporaryDirectory() as directory:
            manifest_path = Path(directory) / "eligibility_sources.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "projects": [
                            {
                                "project_id": "proj_d001",
                                "aliases": ["d001_from_manifest"],
                                "protocol_path": str(D001_PROTOCOL),
                                "source_entry": "d001_protocol_v1_0",
                                "source_version": "V1.0 / 2025-12-21",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            service = EligibilityProtocolRuleService(
                manifest_path=manifest_path
            )

            rules = service.rules_for_project("d001_from_manifest")

        self.assertEqual("proj_d001", rules.project_id)
        self.assertEqual("d001_protocol_v1_0", rules.source_entry)

    def test_both_projects_have_independently_parsed_inclusion_and_exclusion_rules(self) -> None:
        self.assertEqual((6, 30), (len(self.d001.inclusion.rules), len(self.d001.exclusion.rules)))
        self.assertEqual((10, 24), (len(self.my009.inclusion.rules), len(self.my009.exclusion.rules)))
        self.assertEqual("proj_d001", self.d001.project_id)
        self.assertEqual("proj_my009_uc", self.my009.project_id)
        self.assertNotEqual(self.d001.source_entry, self.my009.source_entry)
        self.assertNotEqual(self.d001.content_hash, self.my009.content_hash)

    @unittest.skipUnless(RUX_PROTOCOL.exists(), "RUX raw protocol is required")
    def test_subject_prefixed_headings_are_parsed_without_project_specific_branching(self) -> None:
        rux = self.service.rules_for_project("rux-03-002")

        self.assertEqual("proj_rux_03_002", rux.project_id)
        self.assertEqual((10, 10), (len(rux.inclusion.rules), len(rux.exclusion.rules)))
        self.assertEqual("docx:paragraph:763", rux.inclusion.source_locator)
        self.assertEqual("docx:paragraph:792", rux.exclusion.source_locator)
        self.assertIn("年龄≥12周岁", rux.inclusion.rules[0].text)
        self.assertIn("AD病程不稳定", rux.exclusion.rules[0].text)

    def test_top_level_rule_ids_are_continuous_and_scoped_to_each_project(self) -> None:
        for snapshot in (self.d001, self.my009):
            self.assertEqual(
                [f"IN-{index:02d}" for index in range(1, len(snapshot.inclusion.rules) + 1)],
                [rule.rule_id for rule in snapshot.inclusion.rules],
            )
            self.assertEqual(
                [f"EX-{index:02d}" for index in range(1, len(snapshot.exclusion.rules) + 1)],
                [rule.rule_id for rule in snapshot.exclusion.rules],
            )
            for rule in (*snapshot.inclusion.rules, *snapshot.exclusion.rules):
                self.assertEqual(snapshot.project_id, rule.project_id)

    def test_public_rule_identity_is_revision_bound_and_labels_system_ids_explicitly(self) -> None:
        for snapshot in (self.d001, self.my009):
            self.assertTrue(snapshot.rule_revision.startswith("eligrulev_"))
            top_rules = (*snapshot.inclusion.rules, *snapshot.exclusion.rules)
            self.assertEqual(len(top_rules), len({rule.criterion_uid for rule in top_rules}))
            for rule in top_rules:
                self.assertTrue(rule.criterion_uid.startswith("eligcrit_"))
                self.assertEqual(snapshot.rule_revision, rule.rule_revision)
                self.assertEqual(rule.review_rule_id, rule.rule_id)
                self.assertEqual(rule.review_rule_id, rule.source_rule_label)
                self.assertEqual("source_sequence_verified", rule.numbering_status)

            public = snapshot.public_dict()
            self.assertEqual(snapshot.rule_revision, public["rule_revision"])
            first = public["inclusion"]["rules"][0]
            self.assertEqual(first["review_rule_id"], first["rule_id"])
            self.assertIn("source_rule_label", first)
            self.assertIn("numbering_status", first)

    def test_numbering_restart_is_resolved_without_binding_identity_to_display_label(self) -> None:
        paragraph = ProtocolParagraph(
            paragraph_index=10,
            text="清晰可归属的排除条款",
            source_locator="docx:paragraph:10",
            num_id="42",
            ilvl=0,
            numbering_format="decimal",
            numbering_level_text="%1.",
            numbering_start=1,
            numbering_start_override=5,
        )

        label, status = _source_number_identity(paragraph, "EX-01", 2)

        self.assertEqual("EX-06", label)
        self.assertEqual("source_sequence_verified", status)

    def test_unverifiable_numbering_marks_only_that_rule_without_blocking_text_identity(self) -> None:
        paragraph = ProtocolParagraph(
            paragraph_index=10,
            text="清晰可归属的入选条款",
            source_locator="docx:paragraph:10",
            num_id="custom",
            ilvl=0,
            numbering_format="bullet",
            numbering_level_text="-",
        )

        label, status = _source_number_identity(paragraph, "IN-01", 1)

        self.assertIsNone(label)
        self.assertEqual("source_number_unconfirmed", status)

    def test_every_rule_node_keeps_original_locator_and_source_provenance(self) -> None:
        for snapshot in (self.d001, self.my009):
            nodes = tuple(_walk(snapshot.inclusion.rules)) + tuple(_walk(snapshot.exclusion.rules))
            self.assertTrue(any(rule.children for rule in nodes))
            for rule in nodes:
                self.assertEqual(snapshot.project_id, rule.project_id)
                self.assertTrue(rule.source_locator.startswith("docx:"))
                self.assertEqual(64, len(rule.content_hash))
                self.assertEqual(snapshot.source_entry, rule.source_entry)
                self.assertEqual(snapshot.source_version, rule.source_version)
                self.assertEqual(snapshot.content_hash, rule.content_hash)
                self.assertTrue(rule.text.strip())
                self.assertNotIn("docx:table:", rule.source_locator)

    def test_formal_body_sections_exclude_synopsis_tables_and_preserve_child_levels(self) -> None:
        self.assertEqual("docx:paragraph:1647", self.d001.inclusion.source_locator)
        self.assertEqual("docx:paragraph:1658", self.d001.exclusion.source_locator)
        self.assertEqual("docx:paragraph:923", self.my009.inclusion.source_locator)
        self.assertEqual("docx:paragraph:950", self.my009.exclusion.source_locator)

        for snapshot in (self.d001, self.my009):
            top_rules = (*snapshot.inclusion.rules, *snapshot.exclusion.rules)
            self.assertTrue(all(rule.source_locator.startswith("docx:paragraph:") for rule in top_rules))
            self.assertFalse(any("docx:table:" in rule.source_locator for rule in top_rules))

        d001_in_04 = self.d001.inclusion.rules[3]
        self.assertEqual(
            ["docx:paragraph:1653", "docx:paragraph:1654", "docx:paragraph:1655"],
            [child.source_locator for child in d001_in_04.children],
        )
        d001_ex_09_note = self.d001.exclusion.rules[8].children[-1]
        self.assertEqual("docx:paragraph:1673", d001_ex_09_note.source_locator)
        self.assertEqual(
            ["docx:paragraph:1674", "docx:paragraph:1675"],
            [child.source_locator for child in d001_ex_09_note.children],
        )

        my009_in_06 = self.my009.inclusion.rules[5]
        self.assertEqual(4, len(my009_in_06.children))
        self.assertEqual("docx:paragraph:932", my009_in_06.children[0].children[0].source_locator)
        self.assertEqual(
            [f"docx:paragraph:{index}" for index in range(991, 1000)],
            [child.source_locator for child in self.my009.exclusion.rules[18].children],
        )

    def test_public_model_does_not_expose_paths_or_directory_labels(self) -> None:
        serialized = json.dumps(
            [self.d001.public_dict(), self.my009.public_dict()],
            ensure_ascii=False,
            sort_keys=True,
        )
        for forbidden in (
            "/Users/",
            "test-D001项目",
            "方案及配套资料",
            "全量-入组",
            "EVF审核",
            "internal_path",
            "protocol_path",
            "content_hash",
            "word_numbering",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_ambiguous_duplicate_body_sections_fail_closed(self) -> None:
        def paragraph(index: int, text: str, *, num_id=None, ilvl=None):
            return ProtocolParagraph(
                paragraph_index=index,
                text=text,
                source_locator=f"docx:paragraph:{index}",
                style_name="heading 2" if num_id is None else "body",
                num_id=num_id,
                ilvl=ilvl,
                outline_level=1 if num_id is None else None,
                numbering_format="decimal" if num_id is not None else "",
                numbering_level_text="%1." if num_id is not None else "",
            )

        paragraphs = []
        for start in (0, 10):
            paragraphs.extend(
                [
                    paragraph(start, "入选标准"),
                    paragraph(start + 1, "入选条款", num_id=f"in-{start}", ilvl=0),
                    paragraph(start + 2, "排除标准"),
                    paragraph(start + 3, "排除条款", num_id=f"ex-{start}", ilvl=0),
                    paragraph(start + 4, "下一章节"),
                ]
            )
        document = ProtocolTextDocument(
            filename="fixture.docx",
            title="fixture",
            paragraphs=paragraphs,
            tables=[],
            spans=[],
        )

        with self.assertRaisesRegex(ValueError, "ambiguous"):
            _find_canonical_section_headings(document)

    def test_project_rule_text_and_hash_are_not_reused_across_projects(self) -> None:
        d001_text = "\n".join(
            rule.text for rule in (*_walk(self.d001.inclusion.rules), *_walk(self.d001.exclusion.rules))
        )
        my009_text = "\n".join(
            rule.text for rule in (*_walk(self.my009.inclusion.rules), *_walk(self.my009.exclusion.rules))
        )

        self.assertNotIn("MY009", d001_text)
        self.assertNotIn("CMS-D001", my009_text)
        self.assertNotEqual(d001_text, my009_text)
        self.assertEqual(hashlib.sha256(D001_PROTOCOL.read_bytes()).hexdigest(), self.d001.content_hash)
        self.assertEqual(hashlib.sha256(MY009_PROTOCOL.read_bytes()).hexdigest(), self.my009.content_hash)

    def test_repeated_calls_are_deterministic_for_each_project(self) -> None:
        for project_id, expected in (
            ("proj_d001", self.d001),
            ("proj_my009_uc", self.my009),
        ):
            actual = self.service.rules_for_project(project_id)
            self.assertEqual(expected, actual)
            self.assertEqual(expected.public_dict(), actual.public_dict())

    def test_first_and_last_top_level_rules_trace_to_original_word_paragraphs(self) -> None:
        expected = (
            (
                self.d001,
                D001_PROTOCOL,
                {
                    "IN-01": ("docx:paragraph:1649", "自愿签署知情同意书"),
                    "IN-06": ("docx:paragraph:1657", "有生育能力的参与者"),
                    "EX-01": ("docx:paragraph:1660", "基线前3个月内存在非斑块状银屑病"),
                    "EX-30": ("docx:paragraph:1716", "研究者认为不合适参加本研究"),
                },
            ),
            (
                self.my009,
                MY009_PROTOCOL,
                {
                    "IN-01": ("docx:paragraph:925", "年龄在18 ~ 70岁"),
                    "IN-10": ("docx:paragraph:949", "同意签署知情同意书"),
                    "EX-01": ("docx:paragraph:952", "目前诊断为CD"),
                    "EX-24": ("docx:paragraph:1004", "受试者存在研究者认为"),
                },
            ),
        )

        for snapshot, path, anchors in expected:
            document = parse_protocol_docx(path.name, path.read_bytes())
            source_by_locator = {
                paragraph.source_locator: paragraph.text for paragraph in document.paragraphs
            }
            top_rules = {
                rule.rule_id: rule
                for rule in (*snapshot.inclusion.rules, *snapshot.exclusion.rules)
            }
            for rule_id, (locator, prefix) in anchors.items():
                rule = top_rules[rule_id]
                self.assertEqual(locator, rule.source_locator)
                self.assertTrue(rule.text.startswith(prefix))
                self.assertEqual(source_by_locator[locator], rule.text)


if __name__ == "__main__":
    unittest.main()
