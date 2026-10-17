"""section_card_builder 独立自测（不依赖主 tests/ 套件）。

运行方式：
    python3 tools/writing/test_section_card_builder.py
    python3 -m unittest discover -s tools/writing -p "test_*.py" -t tools/writing
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import section_card_builder as builder  # noqa: E402

SECTION_CARD_KEYS = {
    "card_id",
    "semantic_node_id",
    "tier",
    "purpose",
    "required_elements",
    "consumes_fact_paths",
    "consumes_clause_ids",
    "style_example_budget",
    "length_range_chars",
    "risk_level",
}


def write_contract(root: Path, node_id: str, title: str, **extra) -> None:
    """在临时模板目录写入一份最小冻结合同。"""
    contracts = root / "chapter_contracts"
    contracts.mkdir(parents=True, exist_ok=True)
    substantive = {
        "fact_requirements": [
            {"fact_path": "design.sample_size", "obligation": "required"},
            {"fact_path": "design.optional_hint", "obligation": "optional"},
        ],
        "claim_requirements": [
            {"claim_type": "sample_size_rationale", "obligation": "required"},
            {"claim_type": "optional_claim", "obligation": "optional"},
        ],
        "structural_object_obligations": [
            {"object_kind": "table", "minimum_occurrences": 1},
        ],
        "project_specific_elements": ["继承声明：测试夹具。"],
    }
    contract = {
        "schema_version": "mw_protocol_v3_contract_v2",
        "chapter_contract_id": f"contract::{node_id}",
        "semantic_node_id": node_id,
        "substantive_content": substantive,
        "conditional_applicability_rules": [],
        "ctq_items": [{"question": "样本量是否可复算？"}],
        **extra,
    }
    (contracts / f"{node_id}.json").write_text(
        json.dumps(contract, ensure_ascii=False), encoding="utf-8"
    )


def write_template_root(root: Path) -> None:
    nodes = [
        {"id": "v2_n_d1", "title_zh": "样本量估算", "section_number": "11.1",
         "body_child_index": 1},
        {"id": "v2_n_q1", "title_zh": "神秘章节", "section_number": "11.2",
         "body_child_index": 2},
        {"id": "v2_n_c1", "title_zh": "研究理论依据", "section_number": "2.1",
         "body_child_index": 3},
    ]
    (root / "node_tree.json").write_text(
        json.dumps(
            {
                "template_id": "tpl_test",
                "heading_style_tree": {"nodes": nodes},
                "outlined_tree": {"nodes": nodes},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def write_tiers(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "tier_by_title_keyword": {
                    "D": ["样本量"],
                    "N": ["依据"],
                },
                "tier_by_node_id": {"C": ["v2_n_c1"]},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def build_fixture(**d1_extra):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_template_root(root)
        d1_fields = {
            "conditional_applicability_rules": [{"condition": "设计为非劣效时"}],
        }
        d1_fields.update(d1_extra)
        write_contract(root, "v2_n_d1", "样本量估算", **d1_fields)
        write_contract(root, "v2_n_q1", "神秘章节")
        write_contract(root, "v2_n_c1", "研究理论依据")
        write_tiers(root / "tiers.json")
        tiers = builder.load_node_tiers(root / "tiers.json")
        cards, stats = builder.build_all(root, tiers)
        return cards, stats


class TestClassification(unittest.TestCase):
    def test_d_by_title_keyword(self) -> None:
        cards, stats = build_fixture()
        d_cards = [c for c in cards if c["semantic_node_id"] == "v2_n_d1"]
        self.assertEqual(len(d_cards), 1)
        self.assertEqual(d_cards[0]["tier"], "D")

    def test_unclassifiable_goes_needs_review(self) -> None:
        cards, stats = build_fixture()
        self.assertNotIn("v2_n_q1", [c["semantic_node_id"] for c in cards])
        reviewed = {n["node_id"] for n in stats["needs_review_nodes"]}
        self.assertIn("v2_n_q1", reviewed)
        self.assertEqual(stats["needs_review_count"], len(stats["needs_review_nodes"]))

    def test_node_id_override_beats_title(self) -> None:
        cards, _ = build_fixture()
        c_cards = [c for c in cards if c["semantic_node_id"] == "v2_n_c1"]
        self.assertEqual(len(c_cards), 1)
        self.assertEqual(c_cards[0]["tier"], "C")

    def test_totals_consistent(self) -> None:
        cards, stats = build_fixture()
        self.assertEqual(stats["total_contracts"], 3)
        self.assertEqual(
            stats["cards_emitted"] + stats["needs_review_count"],
            stats["total_contracts"],
        )
        self.assertEqual(stats["cards_emitted"], len(cards))


class TestCardSchema(unittest.TestCase):
    def test_schema_keys_complete(self) -> None:
        cards, _ = build_fixture()
        for card in cards:
            self.assertEqual(set(card.keys()), SECTION_CARD_KEYS)
            self.assertIn(card["tier"], ("D", "C", "N"))
            self.assertIn(card["risk_level"], ("high", "medium", "low"))
            self.assertEqual(len(card["length_range_chars"]), 2)

    def test_purpose_limited_to_80_chars(self) -> None:
        cards, _ = build_fixture()
        for card in cards:
            self.assertLessEqual(len(card["purpose"]), 80)

    def test_required_elements_only_required(self) -> None:
        cards, _ = build_fixture()
        card = next(c for c in cards if c["semantic_node_id"] == "v2_n_d1")
        self.assertIn("claim:sample_size_rationale", card["required_elements"])
        self.assertIn("fact:design.sample_size", card["required_elements"])
        self.assertIn("structural:table", card["required_elements"])
        self.assertNotIn("fact:design.optional_hint", card["required_elements"])
        self.assertNotIn("claim:optional_claim", card["required_elements"])

    def test_consumes_fact_paths_includes_conditional(self) -> None:
        cards, _ = build_fixture(
            conditional_applicability_rules=[
                {"condition": "设计为非劣效时",
                 "triggering_fact_paths": ["design.margin"]},
            ],
        )
        card = next(c for c in cards if c["semantic_node_id"] == "v2_n_d1")
        self.assertIn("design.sample_size", card["consumes_fact_paths"])
        self.assertIn("design.margin", card["consumes_fact_paths"])
        # 去重
        self.assertEqual(len(card["consumes_fact_paths"]),
                         len(set(card["consumes_fact_paths"])))

    def test_risk_heuristic(self) -> None:
        cards, _ = build_fixture()
        d_card = next(c for c in cards if c["semantic_node_id"] == "v2_n_d1")
        self.assertEqual(d_card["risk_level"], "high")
        c_card = next(c for c in cards if c["semantic_node_id"] == "v2_n_c1")
        self.assertEqual(c_card["risk_level"], "medium")

    def test_clause_ids_empty_until_clausebank_exists(self) -> None:
        cards, _ = build_fixture()
        for card in cards:
            self.assertEqual(card["consumes_clause_ids"], [])


class TestShippedDataFiles(unittest.TestCase):
    def test_shipped_node_tiers_load(self) -> None:
        rules = builder.load_node_tiers(HERE / "node_tiers.json")
        self.assertEqual(set(rules["tier_by_title_keyword"]), {"D", "C", "N"})
        self.assertTrue(set(rules["tier_by_node_id"]) <= {"D", "C", "N"})

    def test_real_template_smoke(self) -> None:
        root = builder.default_template_root()
        if not (root / "chapter_contracts").exists():
            self.skipTest("真实模板不在本环境")
        tiers = builder.load_node_tiers(HERE / "node_tiers.json")
        cards, stats = builder.build_all(root, tiers)
        self.assertEqual(stats["total_contracts"], 111)
        self.assertGreater(stats["cards_emitted"], 0)
        self.assertGreater(stats["needs_review_count"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
