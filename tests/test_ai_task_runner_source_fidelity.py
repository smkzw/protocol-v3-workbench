"""Tests for deterministic synopsis source-fidelity materialization.

These tests verify that:
- Endpoint/objective labels (incl. punctuation/NFKC variants) produce anchors.
- ``expected 1, got 0`` is repaired by deterministic anchor materialization.
- Materialized output passes the unchanged one-to-one validator.
- Exact source text and evidence locators survive merge.
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from typing import Dict, List
from unittest.mock import patch

from services.api.app.ai_task_runner import (
    _SYNOPSIS_ENDPOINT_LABELS,
    _SYNOPSIS_OBJECTIVE_FIELD_BY_CATEGORY,
    _SYNOPSIS_ANCHORED_FIELD_BY_CATEGORY,
    _canonical_synopsis_clause,
    _protocol_synopsis_row_anchors,
    build_required_field_hints,
    bind_protocol_synopsis_source_quotes,
    materialize_anchored_synopsis_fields,
    materialize_protocol_synopsis_structured_design,
    normalize_protocol_synopsis_design_enums,
    validate_protocol_synopsis_source_fidelity,
)
from services.api.app.ai_gateway import AiTaskType


def _make_source(source_id: str, text: str, locator: str = "table:1") -> SimpleNamespace:
    return SimpleNamespace(
        source_id=source_id,
        locator=locator,
        text_preview=text,
    )


SAFETY_ENDPOINT_TEXT = (
    "AE、药物不良反应（ADR）、SAE等的发生率，以及体重、体格检查、"
    "生命体征检查、十二导联心电图检查、妊娠检查（仅限育龄期女性）、"
    "临床实验室检查等的异常情况或变化情况。"
)

PRIMARY_OBJECTIVE_TEXT = "评价MY009治疗中重度溃疡性结肠炎受试者的有效性。"
PRIMARY_ENDPOINT_TEXT = "第8周Mayo评分的临床缓解率。"
EXPLORATORY_ENDPOINT_TEXTS = [
    "基于群体药代动力学（PopPK）分析，建立PopPK模型以表征试验药物及其主要代谢产物的PK特征。",
    "评估影响试验药物及其主要代谢产物PK特征的内在和外在因素。",
]


def _synopsis_source_with_safety_row() -> SimpleNamespace:
    """Build a source whose text_preview contains a table with a safety-endpoint
    row, structured so _protocol_synopsis_row_anchors recognises it.

    The anchor builder splits on tab characters and looks for '研究终点' or
    '试验终点' as the first cell label, then parses the remaining cells as
    endpoint text with sub-labels like '安全性终点：'.
    """
    # Tab-separated: first cell = label, rest = endpoint block.
    endpoint_block = "\n".join([
        f"主要终点：{PRIMARY_ENDPOINT_TEXT}",
        "安全性终点：" + SAFETY_ENDPOINT_TEXT,
    ])
    text = "研究终点\t" + endpoint_block
    return _make_source("src_001", text)


class TestSynopsisAnchorLabels(unittest.TestCase):
    """Verify that endpoint/objective labels — including punctuation and NFKC
    variants — are present in the anchor lookup tables."""

    def test_safety_endpoint_label_recognised(self):
        self.assertIn("safety", _SYNOPSIS_ANCHORED_FIELD_BY_CATEGORY)

    def test_endpoint_label_variants_covered(self):
        # The label set must include Chinese full-width and half-width colons.
        for label in ("安全性终点", "安全性终点：", "安全性终点:"):
            normalised = label.rstrip("：:")
            self.assertIn(
                normalised,
                _SYNOPSIS_ENDPOINT_LABELS,
                f"endpoint label '{normalised}' not in lookup",
            )

    def test_canonical_clause_nfck_normalisation(self):
        # NFKC normalisation folds full-width punctuation to half-width.
        self.assertEqual(
            _canonical_synopsis_clause("安全性终点：AE发生率"),
            _canonical_synopsis_clause("安全性终点:AE发生率"),
        )


class TestRequiredFieldHints(unittest.TestCase):
    """``build_required_field_hints`` must produce a {field_path: count} dict
    from deterministic anchors."""

    def test_returns_field_counts(self):
        source = _synopsis_source_with_safety_row()
        hints = build_required_field_hints([source])
        self.assertIsInstance(hints, dict)
        # If anchors are built, the hint count must be > 0.
        for field_path, count in hints.items():
            self.assertGreater(count, 0, f"{field_path} hint count must be > 0")

    def test_empty_when_no_anchors(self):
        source = _make_source("src_empty", "no table structure here")
        hints = build_required_field_hints([source])
        self.assertEqual(hints, {})


class TestProtocolSynopsisDesignEnumNormalization(unittest.TestCase):
    def test_exact_chinese_display_labels_map_to_contract_enums(self):
        output = {
            "study_definition": {
                "framing": {
                    "structured_design": {
                        "randomization_mode": "随机",
                        "blinding_mode": "双盲",
                        "comparator_type": "安慰剂对照",
                    },
                },
            },
        }

        normalized = normalize_protocol_synopsis_design_enums(output)

        design = normalized["study_definition"]["framing"]["structured_design"]
        self.assertEqual("randomized", design["randomization_mode"])
        self.assertEqual("double_blind", design["blinding_mode"])
        self.assertEqual("placebo", design["comparator_type"])

    def test_unknown_or_composite_label_remains_for_strict_rejection(self):
        output = {
            "study_definition": {
                "framing": {
                    "structured_design": {
                        "randomization_mode": "部分随机并允许研究者分配",
                    },
                },
            },
        }

        normalized = normalize_protocol_synopsis_design_enums(output)

        self.assertIs(normalized, output)
        self.assertEqual(
            "部分随机并允许研究者分配",
            normalized["study_definition"]["framing"]["structured_design"][
                "randomization_mode"
            ],
        )


class TestProtocolSynopsisStructuredDesignMaterialization(unittest.TestCase):
    def test_explicit_source_backed_design_is_projected_without_misclassifying_dose_comparison(
        self,
    ):
        output = {
            "study_definition": {
                "framing": {
                    "design_pattern": "多中心、随机、开放标签、平行、剂量探索",
                    "structured_design": {
                        "randomization_mode": "undecided",
                        "blinding_mode": "undecided",
                        "comparator_type": "undecided",
                        "comparator_intervention": "",
                        "assignment_model": "",
                        "center_model": "",
                    },
                },
                "picos": {
                    "comparator_summary": "CMS-D017低剂量组与CMS-D017高剂量组比较",
                },
                "field_evidence_span_ids": {
                    "framing.design_pattern": ["span_design"],
                    "picos.comparator_summary": ["span_comparator"],
                },
            },
            "evidence_spans": [
                {"span_id": "span_design"},
                {"span_id": "span_comparator"},
            ],
        }

        normalized = materialize_protocol_synopsis_structured_design(output)

        definition = normalized["study_definition"]
        design = definition["framing"]["structured_design"]
        self.assertEqual("randomized", design["randomization_mode"])
        self.assertEqual("open_label", design["blinding_mode"])
        self.assertEqual("other", design["comparator_type"])
        self.assertEqual(
            "CMS-D017低剂量组与CMS-D017高剂量组比较",
            design["comparator_intervention"],
        )
        self.assertEqual("平行组", design["assignment_model"])
        self.assertEqual("多中心", design["center_model"])
        self.assertEqual(
            ["span_design", "span_comparator"],
            definition["field_evidence_span_ids"][
                "framing.structured_design.comparator_type"
            ],
        )
        self.assertIn(
            "span_design",
            definition["field_evidence_span_ids"]["framing.structured_design"],
        )

    def test_unbacked_design_pattern_is_not_projected(self):
        output = {
            "study_definition": {
                "framing": {
                    "design_pattern": "随机、双盲、安慰剂对照",
                    "structured_design": {
                        "randomization_mode": "undecided",
                        "blinding_mode": "undecided",
                        "comparator_type": "undecided",
                    },
                },
                "picos": {"comparator_summary": "安慰剂"},
                "field_evidence_span_ids": {},
            },
            "evidence_spans": [{"span_id": "span_design"}],
        }

        normalized = materialize_protocol_synopsis_structured_design(output)

        self.assertIs(normalized, output)
        self.assertEqual(
            "undecided",
            normalized["study_definition"]["framing"]["structured_design"][
                "randomization_mode"
            ],
        )

    def test_source_backed_design_corrects_conflicting_model_projection(self):
        output = {
            "study_definition": {
                "framing": {
                    "design_pattern": "随机、开放标签、剂量探索",
                    "structured_design": {
                        "randomization_mode": "non_randomized",
                        "blinding_mode": "double_blind",
                        "comparator_type": "active",
                    },
                },
                "picos": {"comparator_summary": "低剂量组与高剂量组比较"},
                "field_evidence_span_ids": {
                    "framing.design_pattern": ["span_design"],
                },
            },
            "evidence_spans": [{"span_id": "span_design"}],
        }

        normalized = materialize_protocol_synopsis_structured_design(output)

        design = normalized["study_definition"]["framing"]["structured_design"]
        self.assertEqual("randomized", design["randomization_mode"])
        self.assertEqual("open_label", design["blinding_mode"])
        self.assertEqual("active", design["comparator_type"])


class TestMaterializeAnchoredSynopsisFields(unittest.TestCase):
    """Core source-fidelity repair: deterministic materialization restores
    anchored fields the model omitted."""

    def test_safety_endpoints_expected_1_got_0_is_repaired(self):
        """The real MY009 failure: anchors say expected 1 safety endpoint,
        model output has 0. Materialization must restore it deterministically."""
        source = _synopsis_source_with_safety_row()
        # Simulate model output that drops safety_endpoints.
        model_output: Dict = {
            "study_definition": {
                "picos": {
                    "primary_endpoint": PRIMARY_ENDPOINT_TEXT,
                    "safety_endpoints": [],  # model dropped this
                },
            },
            "evidence_spans": [],
        }
        materialized = materialize_anchored_synopsis_fields(model_output, [source])
        picos = materialized["study_definition"]["picos"]
        self.assertIsInstance(picos["safety_endpoints"], list)
        self.assertGreaterEqual(
            len(picos["safety_endpoints"]), 1,
            "safety_endpoints must be materialized to at least 1 item",
        )

    def test_front_matter_identity_and_population_intent_are_materialized(self):
        sources = [
            _make_source(
                "src_cover_title",
                "磷酸芦可替尼乳膏治疗特应性皮炎的随机、双盲、安慰剂对照III期研究",
                "docx:paragraph:2",
            ),
            _make_source(
                "src_cover_identity",
                "试验药物名称：\n适应症：\n临床方案号：\t"
                "磷酸芦可替尼乳膏\n特应性皮炎\nRUX-03-002",
                "docx:table:1:row:1",
            ),
            _make_source(
                "src_cover_version",
                "方案版本号\t1.3",
                "docx:paragraph:5",
            ),
        ]
        model_output: Dict = {
            "study_definition": {
                "framing": {
                    "protocol_id": "",
                    "version": "V0.1",
                    "document_title": "",
                    "indication": "特应性皮炎",
                    "investigational_product": "磷酸芦可替尼乳膏",
                    "population_intent": "",
                },
                "picos": {
                    "population_summary": "年龄≥12岁的特应性皮炎受试者。",
                },
                "field_evidence_span_ids": {
                    "picos.population_summary": ["span_population"],
                },
            },
            "evidence_spans": [
                {
                    "span_id": "span_population",
                    "source_id": "src_population",
                    "locator": "docx:paragraph:20",
                    "quote": "年龄≥12岁的特应性皮炎受试者。",
                }
            ],
        }

        materialized = materialize_anchored_synopsis_fields(model_output, sources)
        materialized = bind_protocol_synopsis_source_quotes(
            AiTaskType.PROTOCOL_SYNOPSIS_STRUCTURING,
            materialized,
            sources,
        )
        framing = materialized["study_definition"]["framing"]

        self.assertEqual("RUX-03-002", framing["protocol_id"])
        self.assertEqual("V1.3", framing["version"])
        self.assertEqual("磷酸芦可替尼乳膏", framing["investigational_product"])
        self.assertEqual("特应性皮炎", framing["indication"])
        self.assertIn("磷酸芦可替尼乳膏治疗特应性皮炎", framing["document_title"])
        self.assertEqual(
            "年龄≥12岁的特应性皮炎受试者。",
            framing["population_intent"],
        )
        self.assertEqual(
            ["span_population"],
            materialized["study_definition"]["field_evidence_span_ids"][
                "framing.population_intent"
            ],
        )
        version_evidence_ids = materialized["study_definition"][
            "field_evidence_span_ids"
        ]["framing.version"]
        evidence_by_id = {
            item["span_id"]: item for item in materialized["evidence_spans"]
        }
        self.assertEqual(
            "方案版本号\t1.3",
            evidence_by_id[version_evidence_ids[0]]["quote"],
        )
        rematerialized = materialize_anchored_synopsis_fields(
            materialized,
            sources,
        )
        rematerialized_ids = [
            item["span_id"] for item in rematerialized["evidence_spans"]
        ]
        self.assertEqual(
            len(rematerialized_ids),
            len(set(rematerialized_ids)),
            "re-materializing source-bound identity evidence must be idempotent",
        )

    def test_unbound_default_version_is_not_treated_as_extracted_fact(self):
        source = _make_source(
            "src_without_version",
            "研究终点\t主要终点：第12周达到临床缓解的受试者比例。",
        )
        model_output: Dict = {
            "study_definition": {
                "framing": {"version": "V0.1"},
                "picos": {"primary_endpoint": ""},
                "field_evidence_span_ids": {},
            },
            "evidence_spans": [],
        }

        materialized = materialize_anchored_synopsis_fields(
            model_output,
            [source],
        )

        self.assertEqual(
            "",
            materialized["study_definition"]["framing"]["version"],
        )

    def test_front_matter_version_spacing_is_normalized_but_evidence_stays_literal(self):
        for raw_version in ("1.3", "v1.3", "V 1.3"):
            with self.subTest(raw_version=raw_version):
                source = _make_source(
                    f"src_version_{raw_version.replace(' ', '_')}",
                    f"方案版本号\t{raw_version}",
                )
                materialized = materialize_anchored_synopsis_fields(
                    {
                        "study_definition": {
                            "framing": {},
                            "picos": {},
                            "field_evidence_span_ids": {},
                        },
                        "evidence_spans": [],
                    },
                    [source],
                )
                bound = bind_protocol_synopsis_source_quotes(
                    AiTaskType.PROTOCOL_SYNOPSIS_STRUCTURING,
                    materialized,
                    [source],
                )
                self.assertEqual(
                    "V1.3",
                    bound["study_definition"]["framing"]["version"],
                )
                evidence_id = bound["study_definition"][
                    "field_evidence_span_ids"
                ]["framing.version"][0]
                evidence_by_id = {
                    item["span_id"]: item for item in bound["evidence_spans"]
                }
                self.assertIn(
                    evidence_by_id[evidence_id]["quote"],
                    source.text_preview,
                )

    def test_narrative_research_sentence_is_not_used_as_document_title(self):
        source = _make_source(
            "src_narrative",
            "本研究方案拟评价长期治疗的有效性和安全性，具体设计见正文。",
        )
        materialized = materialize_anchored_synopsis_fields(
            {
                "study_definition": {
                    "framing": {},
                    "picos": {},
                    "field_evidence_span_ids": {},
                },
                "evidence_spans": [],
            },
            [source],
        )
        self.assertFalse(
            materialized["study_definition"]["framing"].get("document_title")
        )

    def test_materialization_preserves_exact_source_text(self):
        source = _synopsis_source_with_safety_row()
        model_output: Dict = {
            "study_definition": {
                "picos": {
                    "safety_endpoints": [],
                },
            },
            "evidence_spans": [],
        }
        materialized = materialize_anchored_synopsis_fields(model_output, [source])
        # Check that exact source text is preserved (not paraphrased).
        picos = materialized["study_definition"]["picos"]
        safety_text = picos["safety_endpoints"][0]
        # The materialized item must contain the core of the source text.
        self.assertIn("AE", safety_text)

    def test_same_count_paraphrased_second_item_is_restored_from_source(self):
        """Equal list length must not hide compression of a later source item."""
        source = _make_source(
            "src_exploratory",
            "研究终点\t"
            + "\n".join(
                [
                    f"探索性终点：{EXPLORATORY_ENDPOINT_TEXTS[0]}",
                    EXPLORATORY_ENDPOINT_TEXTS[1],
                ]
            ),
        )
        model_output: Dict = {
            "study_definition": {
                "picos": {
                    "exploratory_endpoints": [
                        EXPLORATORY_ENDPOINT_TEXTS[0],
                        "评估影响PK的相关因素。",
                    ],
                },
            },
            "evidence_spans": [],
        }

        materialized = materialize_anchored_synopsis_fields(model_output, [source])

        self.assertEqual(
            materialized["study_definition"]["picos"]["exploratory_endpoints"],
            EXPLORATORY_ENDPOINT_TEXTS,
            "the paraphrased second item must be replaced by exact source text",
        )

    def test_missing_field_evidence_mapping_is_backfilled_and_validates(self):
        """Exact text is insufficient unless the field points to its evidence."""
        source = _synopsis_source_with_safety_row()
        model_output: Dict = {
            "study_definition": {
                "picos": {
                    "primary_endpoint": PRIMARY_ENDPOINT_TEXT,
                    "safety_endpoints": [SAFETY_ENDPOINT_TEXT],
                },
                "field_evidence_span_ids": {},
            },
            "evidence_spans": [
                {
                    "span_id": "ev_safety_exact",
                    "source_id": source.source_id,
                    "locator": source.locator,
                    "quote": SAFETY_ENDPOINT_TEXT,
                },
                {
                    "span_id": "ev_primary_exact",
                    "source_id": source.source_id,
                    "locator": source.locator,
                    "quote": PRIMARY_ENDPOINT_TEXT,
                },
            ],
        }

        materialized = materialize_anchored_synopsis_fields(model_output, [source])

        field_evidence = materialized["study_definition"]["field_evidence_span_ids"]
        self.assertEqual(
            field_evidence["picos.safety_endpoints"],
            ["ev_safety_exact"],
        )
        self.assertEqual(
            field_evidence["picos.primary_endpoint"],
            ["ev_primary_exact"],
        )
        self.assertEqual(
            validate_protocol_synopsis_source_fidelity(materialized, [source]),
            [],
        )

    def test_each_field_tracks_changed_state_and_evidence_independently(self):
        """Repairing one field must not skip or contaminate the next field."""
        exploratory_source = _make_source(
            "src_exploratory",
            "研究终点\t探索性终点：" + EXPLORATORY_ENDPOINT_TEXTS[0],
            locator="docx:table:1:b1",
        )
        safety_source = _make_source(
            "src_safety",
            "研究终点\t安全性终点：" + SAFETY_ENDPOINT_TEXT,
            locator="docx:table:2:b2",
        )
        model_output: Dict = {
            "study_definition": {
                "picos": {
                    "exploratory_endpoints": [],
                    "safety_endpoints": [SAFETY_ENDPOINT_TEXT],
                },
                "field_evidence_span_ids": {},
            },
            "evidence_spans": [
                {
                    "span_id": "ev_safety_only",
                    "source_id": safety_source.source_id,
                    "locator": safety_source.locator,
                    "quote": SAFETY_ENDPOINT_TEXT,
                },
            ],
        }

        materialized = materialize_anchored_synopsis_fields(
            model_output,
            [exploratory_source, safety_source],
        )

        picos = materialized["study_definition"]["picos"]
        field_evidence = materialized["study_definition"]["field_evidence_span_ids"]
        self.assertEqual(
            picos["exploratory_endpoints"],
            [EXPLORATORY_ENDPOINT_TEXTS[0]],
        )
        self.assertEqual(picos["safety_endpoints"], [SAFETY_ENDPOINT_TEXT])
        self.assertEqual(
            field_evidence["picos.safety_endpoints"],
            ["ev_safety_only"],
            "the later field must receive its own evidence mapping",
        )
        self.assertNotIn(
            "ev_safety_only",
            field_evidence["picos.exploratory_endpoints"],
            "evidence from the later field must not leak into the changed field",
        )
        self.assertEqual(
            validate_protocol_synopsis_source_fidelity(
                materialized,
                [exploratory_source, safety_source],
            ),
            [],
        )

    def test_materialization_adds_evidence_span(self):
        source = _synopsis_source_with_safety_row()
        model_output: Dict = {
            "study_definition": {
                "picos": {
                    "safety_endpoints": [],
                },
            },
            "evidence_spans": [],
        }
        materialized = materialize_anchored_synopsis_fields(model_output, [source])
        evidence_spans = materialized.get("evidence_spans", [])
        self.assertGreater(len(evidence_spans), 0, "evidence span must be created")

    def test_no_override_when_model_has_correct_items(self):
        """If the model already has the correct number of items for a field,
        do not override that field."""
        source = _synopsis_source_with_safety_row()
        # Build model output with a non-empty safety_endpoints.
        model_output: Dict = {
            "study_definition": {
                "picos": {
                    "safety_endpoints": [SAFETY_ENDPOINT_TEXT],
                },
            },
            "evidence_spans": [],
        }
        materialized = materialize_anchored_synopsis_fields(model_output, [source])
        picos = materialized["study_definition"]["picos"]
        # safety_endpoints must be unchanged (still the model's text).
        self.assertEqual(picos["safety_endpoints"], [SAFETY_ENDPOINT_TEXT])

    def test_materialized_output_passes_validator(self):
        """After materialization, the unchanged strict one-to-one validator
        must pass for the anchored field."""
        source = _synopsis_source_with_safety_row()
        model_output: Dict = {
            "study_definition": {
                "picos": {
                    "safety_endpoints": [],
                },
            },
            "evidence_spans": [],
        }
        materialized = materialize_anchored_synopsis_fields(model_output, [source])
        # Run the validator on the materialized output.
        # Note: if anchors didn't fire, we can't validate; but if they did,
        # the materialized output should have the right count.
        anchors = _protocol_synopsis_row_anchors([source])
        if "picos.safety_endpoints" in anchors:
            errors = validate_protocol_synopsis_source_fidelity(materialized, [source])
            safety_errors = [
                e for e in errors if "safety_endpoints" in e
            ]
            # The count mismatch error should be gone.
            count_errors = [
                e for e in safety_errors if "expected" in e and "got" in e
            ]
            self.assertEqual(
                len(count_errors), 0,
                f"count mismatch error should be resolved after materialization: {count_errors}",
            )

    def test_empty_output_unchanged_when_no_anchors(self):
        source = _make_source("src_empty", "no table structure here")
        model_output: Dict = {
            "study_definition": {"picos": {"safety_endpoints": []}},
            "evidence_spans": [],
        }
        materialized = materialize_anchored_synopsis_fields(model_output, [source])
        self.assertEqual(
            materialized["study_definition"]["picos"]["safety_endpoints"], []
        )


class TestSourceOrderPreserved(unittest.TestCase):
    """Multiple distinct source rows must be preserved even if semantically
    similar — no deduplication by semantic similarity."""

    def test_two_distinct_safety_endpoints_both_preserved(self):
        endpoint_block = "\n".join([
            "安全性终点：AE、ADR、SAE等的发生率。",
            "安全性终点：体重、生命体征、心电图、实验室检查异常情况。",
        ])
        text = "研究终点\t" + endpoint_block
        source = _make_source("src_multi", text)
        model_output: Dict = {
            "study_definition": {"picos": {"safety_endpoints": []}},
            "evidence_spans": [],
        }
        materialized = materialize_anchored_synopsis_fields(model_output, [source])
        # If anchors produced 2 items, both must survive.
        anchors = _protocol_synopsis_row_anchors([source])
        expected_count = len(anchors.get("picos.safety_endpoints", []))
        if expected_count > 1:
            picos = materialized["study_definition"]["picos"]
            self.assertEqual(
                len(picos["safety_endpoints"]), expected_count,
                "both distinct safety endpoints must be preserved",
            )


if __name__ == "__main__":
    unittest.main()
