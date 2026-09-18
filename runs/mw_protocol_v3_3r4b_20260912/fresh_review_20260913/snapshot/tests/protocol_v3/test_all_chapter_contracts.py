"""Task3R.3 red-first tests for the typed chapter registry core.

Scope: loader for per-node embedded ``ChapterContractV2`` registries with
companion chapter-skill manifests and closed fact/claim vocabularies, the
cross-contract linter (coverage derived from the template node tree, never
hardcoded), and the deterministic positive/negative fixture checker.

These tests are offline and deterministic: no service, model, OCR,
translation, repository or network is touched.  Clinical authoring is out of
scope — the fixtures below are representative synthetic medical and
metadata/control payloads bound to accepted registry identities.
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.protocol_workflow.registries.chapters import (
    CHAPTER_REGISTRY_SCHEMA_VERSION,
    CHAPTER_SKILL_INPUT_SCHEMA_REF,
    CHAPTER_SKILL_OUTPUT_SCHEMA_REF,
    ChapterFixture,
    ChapterRegistryDocument,
    ChapterSkillInput,
    ChapterSkillManifest,
    ChapterSkillOutput,
    RegistryDocumentError,
    check_fixture,
    check_skill_output,
    lint_registry,
    load_chapter_registry,
    resolve_schema_ref,
)
from packages.contracts.workbench_contracts.protocol_v3 import (
    ChapterContractV2,
    WordFormattingRules,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_TEMPLATE_DIR = REPO_ROOT / "config/medical_writing/protocol_v3/templates/tp_ma_07_v2"
TEMPLATE_ID = "tp_ma_07_v2"
#: Frozen source sha256 recorded by the accepted 3R.1 candidate registry.
TEMPLATE_SHA256 = (
    "018d28d37b3e58ee97f41414371b78fc9251cbe0942f0b8baa875948bb143756"
)

FACT_VOCABULARY = (
    "picos.objective.primary",
    "picos.population.adult",
    "picos.risk.pregnancy_contraception",
    "provenance.template.version",
    "provenance.appendix.child_manifest",
    "glossary.term_count",
)
CLAIM_VOCABULARY = (
    "study_objective",
    "efficacy_superiority",
    "safety_tolerability",
    "marketing_claim",
)


# ---------------------------------------------------------------------------
# ChapterContractV2 builders bound to accepted registry identities.
# ---------------------------------------------------------------------------


def _objectives_contract(**overrides) -> ChapterContractV2:
    payload = {
        "chapter_contract_id": "contract:v2-n-3-1-1:v2",
        "semantic_node_id": "v2_n_3_1_1",
        "contract_version": "3.1.0",
        "template_id": TEMPLATE_ID,
        "template_sha256": TEMPLATE_SHA256,
        "chapter_skill_id": "skill:chapter:primary-objective",
        "chapter_skill_version": "3.1.0",
        "substantive_content": {
            "substantive_content_contract_id": "content:v2-n-3-1-1:v2",
            "chapter_contract_id": "contract:v2-n-3-1-1:v2",
            "fact_requirements": (
                {
                    "fact_path": "picos.objective.primary",
                    "obligation": "required",
                    "rationale": "主要目的章必须回链已确认的主要目的事实。",
                },
                {
                    "fact_path": "picos.population.adult",
                    "obligation": "optional",
                    "rationale": "仅在人群声明涉及成人年龄界值时引用。",
                },
                {
                    "fact_path": "picos.risk.pregnancy_contraception",
                    "obligation": "optional",
                    "rationale": "由条件规则在人群包含育龄女性时升级为必须。",
                },
            ),
            "claim_requirements": (
                {
                    "claim_type": "study_objective",
                    "obligation": "required",
                    "rationale": "研究目的章必须声明主要目的。",
                },
                {
                    "claim_type": "efficacy_superiority",
                    "obligation": "qualified",
                    "qualifying_conditions": (
                        "仅在主要终点显著且与已采信竞品证据一致时",
                    ),
                    "rationale": "优效表述必须满足限定条件。",
                },
                {
                    "claim_type": "marketing_claim",
                    "obligation": "forbidden",
                    "rationale": "协议正文禁止营销性表述。",
                },
            ),
            "evidence_source_requirements": (
                {
                    "source_roles": ("competitor_full_protocol", "regulatory_or_guideline"),
                    "admission_claim_types": ("study_objective",),
                    "allowed_locator_kinds": ("body", "table"),
                    "require_context_window": True,
                    "minimum_quality_score": 0.85,
                },
            ),
            "structural_object_obligations": (
                {
                    "object_kind": "paragraph",
                    "minimum_occurrences": 2,
                    "project_specific_specification": "主要目的段必须逐条映射 UC301 主要目的与主要估计目标。",
                },
                {
                    "object_kind": "table",
                    "minimum_occurrences": 1,
                    "project_specific_specification": "主要终点对照表必须给出 UC301 主要终点行。",
                    "required_object_cells": ("estimand:table:primary_endpoint",),
                },
            ),
            "project_specific_elements": ("UC301 主要目的与主要估计目标映射",),
            "skeleton_risk_rules": ("只有标题或通用模板句即失败",),
        },
        "word_rules": {
            "word_formatting_rules_id": "word:rules:primary-objective",
            "required_styles": ("Heading 3", "List Paragraph"),
            "forbidden_styles": ("Heading 1",),
            "required_bookmarks": ("bm_primary_objective",),
            "required_cross_references": ("soa_table_1",),
        },
        "positive_qc_rules": (
            {
                "positive_qc_rule_id": "qc:primary-objective:mapping",
                "rule": "主要目的必须与主要估计目标一一映射并给出事实路径回链。",
            },
        ),
        "conditional_applicability_rules": (
            {
                "conditional_applicability_rule_id": "applicability:contraception",
                "triggering_fact_paths": ("picos.population.adult",),
                "condition": "已确认人群包含育龄女性",
                "rationale": "妊娠避孕义务仅在人群包含育龄女性时生效。",
                "required_when_active_fact_paths": ("picos.risk.pregnancy_contraception",),
                "required_when_active_structural_objects": ("paragraph",),
            },
        ),
        "ctq_items": (
            {
                "ctq_item_id": "ctq:primary-objective:mapping",
                "question": "主要目的是否与主要估计目标一一映射？",
                "linked_fact_paths": ("picos.objective.primary",),
                "linked_claim_types": ("study_objective",),
                "positive_qc_rule_ids": ("qc:primary-objective:mapping",),
                "risk_if_unmet": "目的与估计目标脱节会导致研究目的章整体不可用。",
            },
        ),
    }
    payload.update(overrides)
    return ChapterContractV2.model_validate(payload)


def _cover_contract(**overrides) -> ChapterContractV2:
    payload = {
        "chapter_contract_id": "contract:v2-front-block:v2",
        "semantic_node_id": "v2_front_block",
        "contract_version": "3.1.0",
        "template_id": TEMPLATE_ID,
        "template_sha256": TEMPLATE_SHA256,
        "chapter_skill_id": "skill:chapter:front-block",
        "chapter_skill_version": "3.1.0",
        "substantive_content": {
            "substantive_content_contract_id": "content:v2-front-block:v2",
            "chapter_contract_id": "contract:v2-front-block:v2",
            "fact_requirements": (
                {
                    "fact_path": "provenance.template.version",
                    "obligation": "required",
                    "rationale": "封面必须承载真实模板/文档版本 provenance。",
                },
            ),
            "structural_object_obligations": (
                {
                    "object_kind": "table",
                    "minimum_occurrences": 1,
                    "project_specific_specification": "封面版本对照表逐行给出 UC301 文档版本与日期。",
                    "required_object_cells": ("doc:control:version",),
                },
            ),
            "project_specific_elements": ("UC301 封面版本 provenance",),
            "skeleton_risk_rules": ("版本表缺失或仅有表头即失败",),
        },
        "word_rules": {
            "word_formatting_rules_id": "word:rules:front-block",
            "required_styles": ("Normal",),
        },
        "positive_qc_rules": (
            {
                "positive_qc_rule_id": "qc:front-block:provenance",
                "rule": "封面版本信息必须与文档控制 provenance 一致。",
            },
        ),
    }
    payload.update(overrides)
    return ChapterContractV2.model_validate(payload)


def _aggregation_contract(**overrides) -> ChapterContractV2:
    payload = {
        "chapter_contract_id": "contract:v2-n-16:v2",
        "semantic_node_id": "v2_n_16",
        "contract_version": "3.1.0",
        "template_id": TEMPLATE_ID,
        "template_sha256": TEMPLATE_SHA256,
        "chapter_skill_id": "skill:chapter:appendix-aggregation",
        "chapter_skill_version": "3.1.0",
        "substantive_content": {
            "substantive_content_contract_id": "content:v2-n-16:v2",
            "chapter_contract_id": "contract:v2-n-16:v2",
            "fact_requirements": (
                {
                    "fact_path": "provenance.appendix.child_manifest",
                    "obligation": "required",
                    "rationale": "附录容器必须逐项列出实际承载附录叶子。",
                },
            ),
            "structural_object_obligations": (
                {
                    "object_kind": "paragraph",
                    "minimum_occurrences": 1,
                    "project_specific_specification": "附录容器仅承载聚合与 Word 书签/交叉引用义务，不新增临床声明。",
                },
            ),
            "project_specific_elements": ("附录聚合清单（v2_n_16_x1/x2/x3）",),
            "skeleton_risk_rules": ("聚合清单缺失即失败",),
        },
        "word_rules": {
            "word_formatting_rules_id": "word:rules:appendix-aggregation",
            "required_bookmarks": ("bm_appendix_container",),
        },
        "positive_qc_rules": (
            {
                "positive_qc_rule_id": "qc:appendix-aggregation:manifest",
                "rule": "附录聚合清单必须与具体附录叶子的实际承载一致。",
            },
        ),
    }
    payload.update(overrides)
    return ChapterContractV2.model_validate(payload)


def _glossary_contract(**overrides) -> ChapterContractV2:
    payload = {
        "chapter_contract_id": "contract:v2-n-front-5:v2",
        "semantic_node_id": "v2_n_front_5",
        "contract_version": "3.1.0",
        "template_id": TEMPLATE_ID,
        "template_sha256": TEMPLATE_SHA256,
        "chapter_skill_id": "skill:chapter:glossary",
        "chapter_skill_version": "3.1.0",
        "substantive_content": {
            "substantive_content_contract_id": "content:v2-n-front-5:v2",
            "chapter_contract_id": "contract:v2-n-front-5:v2",
            "fact_requirements": (
                {
                    "fact_path": "glossary.term_count",
                    "obligation": "required",
                    "rationale": "缩略语表必须记录实际术语数量 provenance。",
                },
            ),
            "structural_object_obligations": (
                {
                    "object_kind": "table",
                    "minimum_occurrences": 1,
                    "project_specific_specification": "缩略语表必须给出缩写与全称两列表头。",
                    "required_object_cells": (
                        "glossary:header:abbreviation",
                        "glossary:header:full_name",
                    ),
                },
            ),
            "project_specific_elements": ("UC301 缩略语表",),
            "skeleton_risk_rules": ("缩略语表仅有表头即失败",),
        },
        "word_rules": {
            "word_formatting_rules_id": "word:rules:glossary",
            "required_styles": ("table",),
        },
        "positive_qc_rules": (
            {
                "positive_qc_rule_id": "qc:glossary:completeness",
                "rule": "缩略语表条目必须覆盖正文出现的全部缩写。",
            },
        ),
    }
    payload.update(overrides)
    return ChapterContractV2.model_validate(payload)


def _skill_payload(
    skill_id: str,
    node_id: str,
    contract_id: str,
    template_id: str = TEMPLATE_ID,
    template_sha256: str = TEMPLATE_SHA256,
    **overrides,
) -> dict:
    payload = {
        "skill_id": skill_id,
        "skill_version": "3.1.0",
        "node_id": node_id,
        "chapter_contract_id": contract_id,
        "template_id": template_id,
        "template_sha256": template_sha256,
        "input_schema_ref": CHAPTER_SKILL_INPUT_SCHEMA_REF,
        "output_schema_ref": CHAPTER_SKILL_OUTPUT_SCHEMA_REF,
        "prompt_contract": {
            "prompt_version": "prompt:v3.1.0",
            "instructions": "按章节合同逐条满足事实/声明/证据/结构义务，禁止编造证据。",
            "forbidden_behaviors": ("编造证据来源", "输出未声明事实"),
        },
        "provenance_requirements": (
            "输出必须记录模板身份与章节合同 material sha256。",
        ),
        "error_codes": (
            "skill:chapter:missing-obligation",
            "skill:chapter:unresolved-fact",
        ),
    }
    payload.update(overrides)
    return payload


def _entry_payload(
    contract: ChapterContractV2, coverage_role: str = "heading_leaf", **overrides
) -> dict:
    contract_id = contract.chapter_contract_id
    payload = {
        "node_id": contract.semantic_node_id,
        "coverage_role": coverage_role,
        "contract": json.loads(contract.model_dump_json()),
        "skills": [
            _skill_payload(
                contract.chapter_skill_id,
                contract.semantic_node_id,
                contract_id,
                template_id=contract.template_id,
                template_sha256=contract.template_sha256,
                skill_version=contract.chapter_skill_version,
            )
        ],
    }
    payload.update(overrides)
    return payload


def _registry_payload(entries: list[dict], fixtures: list[dict] | None = None) -> dict:
    return {
        "schema_version": CHAPTER_REGISTRY_SCHEMA_VERSION,
        "generated_for": "tp-ma-07 v2 chapter contracts (3R.3)",
        "authority": "Codex-approved Plan v2 Task 3R.3",
        "template_id": TEMPLATE_ID,
        "template_sha256": TEMPLATE_SHA256,
        "fact_vocabulary": list(FACT_VOCABULARY),
        "claim_vocabulary": list(CLAIM_VOCABULARY),
        "chapters": entries,
        "fixtures": fixtures or [],
    }


def _fixture_payload(
    fixture_id: str, contract_id: str, kind: str, content: dict, **overrides
) -> dict:
    payload = {
        "fixture_id": fixture_id,
        "chapter_contract_id": contract_id,
        "fixture_kind": kind,
        "content": content,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Content payload builders (representative synthetic medical / control data).
# ---------------------------------------------------------------------------


def _objectives_positive_content() -> dict:
    return {
        "facts": [
            {"fact_path": "picos.objective.primary", "value": "评价 UC301 在 UC 中的主要目的（已确认事实）。"},
            {"fact_path": "picos.population.adult", "value": "18-75 岁成人。"},
        ],
        "claims": [
            {"claim_type": "study_objective", "statement": "主要目的：评价 UC301 诱导 12 周临床缓解的疗效。"},
        ],
        "evidence": [
            {
                "source_role": "competitor_full_protocol",
                "admission_claim_type": "study_objective",
                "locator_kind": "body",
                "locator": "竞品完整方案 §5.1 主要目的",
                "context": "竞品方案 §5.1 上下文窗口：目的与终点定义原文。",
                "quality_score": 0.92,
            },
        ],
        "objects": [
            {
                "object_kind": "paragraph",
                "occurrences": 2,
                "text": "主要目的段与主要估计目标映射段（实际正文）。",
            },
            {
                "object_kind": "table",
                "occurrences": 1,
                "cells": [
                    {"cell_id": "estimand:table:primary_endpoint", "value": "12 周临床缓解率"},
                ],
            },
        ],
    }


def _cover_positive_content() -> dict:
    return {
        "facts": [
            {"fact_path": "provenance.template.version", "value": "TP-MA-07 v2.0 20260905"},
        ],
        "objects": [
            {
                "object_kind": "table",
                "occurrences": 1,
                "cells": [
                    {"cell_id": "doc:control:version", "value": "v2.0 20260905"},
                ],
            },
        ],
    }


# ---------------------------------------------------------------------------
# Loader: compact layout round-trip and fail-closed negatives.
# ---------------------------------------------------------------------------


def test_compact_json_layout_roundtrip_and_typed_access(tmp_path):
    entries = [
        _entry_payload(_cover_contract(), "cover"),
        _entry_payload(_objectives_contract(), "heading_leaf"),
        _entry_payload(_aggregation_contract(), "heading_only_aggregation"),
        _entry_payload(_glossary_contract(), "outline_only_leaf"),
    ]
    fixtures = [
        _fixture_payload(
            "fixture:cover:positive",
            "contract:v2-front-block:v2",
            "positive",
            _cover_positive_content(),
        ),
        _fixture_payload(
            "fixture:objectives:positive",
            "contract:v2-n-3-1-1:v2",
            "positive",
            _objectives_positive_content(),
        ),
    ]
    payload = _registry_payload(entries, fixtures)
    path = tmp_path / "chapter_registry.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    document = load_chapter_registry(path)
    assert isinstance(document, ChapterRegistryDocument)
    assert document.schema_version == CHAPTER_REGISTRY_SCHEMA_VERSION
    assert [entry.node_id for entry in document.chapters] == [
        "v2_front_block",
        "v2_n_3_1_1",
        "v2_n_16",
        "v2_n_front_5",
    ]
    objectives = document.chapters[1]
    assert isinstance(objectives.contract, ChapterContractV2)
    assert objectives.contract.chapter_skill_id == "skill:chapter:primary-objective"
    assert objectives.skills[0].skill_version == "3.1.0"
    assert objectives.contract.substantive_content.fact_requirements[0].fact_path == (
        "picos.objective.primary"
    )
    assert document.fixtures[1].fixture_kind == "positive"

    # The compact JSON layout documented in the module survives a round-trip.
    restored = load_chapter_registry(json.loads(json.dumps(payload)))
    assert restored == document
    # The loader does not mutate the caller's payload.
    snapshot = copy.deepcopy(payload)
    load_chapter_registry(payload)
    assert payload == snapshot


def test_loader_fails_closed_on_unknown_field_or_bad_template_hash(tmp_path):
    payload = _registry_payload([_entry_payload(_cover_contract(), "cover")])
    payload["unexpected_top_level"] = "no"
    with pytest.raises(RegistryDocumentError):
        load_chapter_registry(payload)

    payload = _registry_payload([_entry_payload(_cover_contract(), "cover")])
    payload["template_sha256"] = "not-a-sha"
    with pytest.raises(RegistryDocumentError):
        load_chapter_registry(payload)

    payload = _registry_payload([_entry_payload(_cover_contract(), "cover")])
    payload["schema_version"] = "protocol-v3-chapter-registry.v999"
    with pytest.raises(RegistryDocumentError):
        load_chapter_registry(payload)


def test_loader_rejects_duplicate_node_entries():
    def mutator(payload):
        payload["chapters"].append(copy.deepcopy(payload["chapters"][0]))

    payload = _registry_payload(
        [
            _entry_payload(_cover_contract(), "cover"),
            _entry_payload(_objectives_contract(), "heading_leaf"),
        ]
    )
    mutator(payload)
    with pytest.raises(RegistryDocumentError):
        load_chapter_registry(payload)


def test_loader_rejects_duplicate_contract_skill_and_fixture_ids():
    cover = _cover_contract()
    objectives = _objectives_contract()
    # Two entries cannot share one chapter contract identity.
    payload = _registry_payload(
        [
            _entry_payload(cover, "cover"),
            _entry_payload(objectives, "heading_leaf"),
        ]
    )
    payload["chapters"][1]["contract"]["chapter_contract_id"] = cover.chapter_contract_id
    payload["chapters"][1]["contract"]["semantic_node_id"] = "v2_n_3_1_1"
    payload["chapters"][1]["node_id"] = "v2_n_3_1_1"
    with pytest.raises(RegistryDocumentError):
        load_chapter_registry(payload)

    # Duplicate skill ids across entries fail closed.
    payload = _registry_payload([_entry_payload(cover, "cover")])
    payload["chapters"][0]["skills"].append(
        _skill_payload(
            "skill:chapter:front-block",
            "v2_front_block",
            "contract:v2-front-block:v2",
        )
    )
    with pytest.raises(RegistryDocumentError):
        load_chapter_registry(payload)

    # Duplicate fixture ids fail closed.
    fixtures = [
        _fixture_payload(
            "fixture:cover:positive",
            "contract:v2-front-block:v2",
            "positive",
            _cover_positive_content(),
        ),
        _fixture_payload(
            "fixture:cover:positive",
            "contract:v2-front-block:v2",
            "missing_control",
            {"facts": [], "objects": []},
        ),
    ]
    payload = _registry_payload([_entry_payload(cover, "cover")], fixtures)
    with pytest.raises(RegistryDocumentError):
        load_chapter_registry(payload)

    # Fixtures must bind to a declared chapter contract.
    payload = _registry_payload(
        [_entry_payload(cover, "cover")],
        [
            _fixture_payload(
                "fixture:ghost:positive",
                "contract:ghost:v2",
                "positive",
                _cover_positive_content(),
            )
        ],
    )
    with pytest.raises(RegistryDocumentError):
        load_chapter_registry(payload)


def test_entry_identity_binding_is_enforced():
    payload = _registry_payload([_entry_payload(_cover_contract(), "cover")])
    payload["chapters"][0]["node_id"] = "v2_n_16"
    with pytest.raises(RegistryDocumentError):
        load_chapter_registry(payload)

    payload = _registry_payload([_entry_payload(_cover_contract(), "cover")])
    payload["chapters"][0]["skills"][0]["node_id"] = "v2_n_16"
    with pytest.raises(RegistryDocumentError):
        load_chapter_registry(payload)

    payload = _registry_payload([_entry_payload(_cover_contract(), "cover")])
    payload["chapters"][0]["skills"][0]["chapter_contract_id"] = "contract:other:v2"
    with pytest.raises(RegistryDocumentError):
        load_chapter_registry(payload)

    payload = _registry_payload([_entry_payload(_cover_contract(), "cover")])
    payload["chapters"][0]["skills"][0]["template_sha256"] = "b" * 64
    with pytest.raises(RegistryDocumentError):
        load_chapter_registry(payload)


# ---------------------------------------------------------------------------
# Chapter skill manifest: shared typed I/O, no model transport.
# ---------------------------------------------------------------------------


def test_skill_manifest_exports_real_typed_io_schemas():
    input_ref_type = resolve_schema_ref(CHAPTER_SKILL_INPUT_SCHEMA_REF)
    output_ref_type = resolve_schema_ref(CHAPTER_SKILL_OUTPUT_SCHEMA_REF)
    assert input_ref_type is ChapterSkillInput
    assert output_ref_type is ChapterSkillOutput

    skill_input = ChapterSkillInput(
        chapter_contract_id="contract:v2-n-3-1-1:v2",
        node_id="v2_n_3_1_1",
        template_id=TEMPLATE_ID,
        template_sha256=TEMPLATE_SHA256,
        resolved_facts={"picos.objective.primary": "已确认的主要目的事实。"},
        word_rules=WordFormattingRules(
            word_formatting_rules_id="word:rules:primary-objective",
            required_styles=("Heading 3",),
        ),
    )
    assert skill_input.resolved_facts["picos.objective.primary"]
    with pytest.raises(Exception):
        ChapterSkillInput(
            chapter_contract_id="contract:v2-n-3-1-1:v2",
            node_id="v2_n_3_1_1",
            template_id=TEMPLATE_ID,
            template_sha256=TEMPLATE_SHA256,
            resolved_facts={"picos.objective.primary": "   "},
            word_rules=WordFormattingRules(
                word_formatting_rules_id="word:rules:blank",
                required_styles=("Heading 3",),
            ),
        )

    skill_output = ChapterSkillOutput(
        chapter_contract_id="contract:v2-n-3-1-1:v2",
        node_id="v2_n_3_1_1",
        claims=[{"claim_type": "study_objective", "statement": "主要目的声明。"}],
    )
    assert skill_output.content_payload().claims[0].claim_type == "study_objective"

    manifest_payload = _skill_payload(
        "skill:chapter:primary-objective", "v2_n_3_1_1", "contract:v2-n-3-1-1:v2"
    )
    assert ChapterSkillManifest.model_validate(manifest_payload)
    # An invented schema URL is not an implemented I/O contract.
    for field in ("input_schema_ref", "output_schema_ref"):
        payload = json.loads(json.dumps(manifest_payload))
        payload[field] = "https://schemas.example.com/invented-chapter-io-v1.json"
        with pytest.raises(Exception):
            ChapterSkillManifest.model_validate(payload)


def test_skill_manifest_carries_no_model_transport_fields():
    """Model choice belongs to the role binding, not the skill transport."""
    declared = set(ChapterSkillManifest.model_fields)
    assert declared
    for forbidden in ("provider", "model", "harness", "reasoning_effort",
                      "allowed_providers", "target_profile"):
        assert forbidden not in declared


# ---------------------------------------------------------------------------
# Fixture checker: deterministic positives/negatives.
# ---------------------------------------------------------------------------


def _make_document():
    entries = [
        _entry_payload(_cover_contract(), "cover"),
        _entry_payload(_objectives_contract(), "heading_leaf"),
    ]
    return load_chapter_registry(_registry_payload(entries))


def _result_codes(result) -> set[str]:
    return {finding.code for finding in result.findings if finding.severity == "error"}


def test_positive_fixture_passes_and_records_deferred_qc():
    document = _make_document()
    fixture = ChapterFixture.model_validate(
        _fixture_payload(
            "fixture:objectives:positive",
            "contract:v2-n-3-1-1:v2",
            "positive",
            _objectives_positive_content(),
        )
    )
    result = check_fixture(document, fixture)
    assert result.passed is True
    assert not _result_codes(result)
    # Deterministic pass never claims the medical/QC judgment happened.
    assert any("positive_qc_rule" in item for item in result.deferred_qc_obligations)
    assert any("ctq" in item for item in result.deferred_qc_obligations)
    assert any("skeleton_risk_rule" in item for item in result.deferred_qc_obligations)


@pytest.mark.parametrize(
    "content, expected_code",
    [
        pytest.param(
            {
                "facts": _objectives_positive_content()["facts"],
                "claims": [],
                "evidence": _objectives_positive_content()["evidence"],
                "objects": _objectives_positive_content()["objects"],
            },
            "missing_required_claim",
            id="claim_absent",
        ),
        pytest.param(
            {
                "facts": _objectives_positive_content()["facts"],
                "claims": [{"claim_type": "study_objective", "statement": "   "}],
                "evidence": _objectives_positive_content()["evidence"],
                "objects": _objectives_positive_content()["objects"],
            },
            "missing_required_claim",
            id="claim_blank_statement",
        ),
        pytest.param(
            {
                "facts": [],
                "claims": _objectives_positive_content()["claims"],
                "evidence": _objectives_positive_content()["evidence"],
                "objects": _objectives_positive_content()["objects"],
            },
            "missing_required_fact",
            id="fact_absent",
        ),
        pytest.param(
            {
                "facts": [{"fact_path": "picos.objective.primary", "value": None}],
                "claims": _objectives_positive_content()["claims"],
                "evidence": _objectives_positive_content()["evidence"],
                "objects": _objectives_positive_content()["objects"],
            },
            "missing_required_fact",
            id="fact_null_value",
        ),
        pytest.param(
            {
                "facts": [{"fact_path": "picos.objective.primary", "value": ""}],
                "claims": _objectives_positive_content()["claims"],
                "evidence": _objectives_positive_content()["evidence"],
                "objects": _objectives_positive_content()["objects"],
            },
            "missing_required_fact",
            id="fact_blank_value",
        ),
    ],
)
def test_missing_claim_and_blank_fact_fail_independently(content, expected_code):
    document = _make_document()
    fixture = ChapterFixture.model_validate(
        _fixture_payload(
            "fixture:objectives:negative",
            "contract:v2-n-3-1-1:v2",
            "missing_claim",
            content,
        )
    )
    result = check_fixture(document, fixture)
    assert result.passed is False
    assert expected_code in _result_codes(result)


def test_wrong_source_role_fails_deterministically():
    document = _make_document()
    content = _objectives_positive_content()
    content["evidence"] = [
        {
            "source_role": "company_style_only",
            "admission_claim_type": "study_objective",
            "locator_kind": "body",
            "locator": "公司风格指南 §2",
            "context": "风格指南上下文窗口。",
            "quality_score": 0.9,
        },
    ]
    fixture = ChapterFixture.model_validate(
        _fixture_payload(
            "fixture:objectives:wrong-source",
            "contract:v2-n-3-1-1:v2",
            "wrong_source",
            content,
        )
    )
    result = check_fixture(document, fixture)
    codes = _result_codes(result)
    assert "wrong_source_role" in codes
    assert "unsatisfied_evidence_requirement" in codes
    assert result.passed is False


@pytest.mark.parametrize(
    "evidence_overrides, expected_code",
    [
        pytest.param(
            {"locator_kind": "figure"},
            "disallowed_locator",
            id="locator_not_allowed",
        ),
        pytest.param({"context": None}, "missing_context_window", id="context_missing"),
        pytest.param({"quality_score": 0.5}, "insufficient_quality", id="quality_low"),
    ],
)
def test_evidence_floor_violations_fail(evidence_overrides, expected_code):
    document = _make_document()
    evidence = json.loads(
        json.dumps(_objectives_positive_content()["evidence"], ensure_ascii=False)
    )
    evidence[0].update(evidence_overrides)
    content = _objectives_positive_content()
    content["evidence"] = evidence
    fixture = ChapterFixture.model_validate(
        _fixture_payload(
            "fixture:objectives:evidence-floor",
            "contract:v2-n-3-1-1:v2",
            "wrong_source",
            content,
        )
    )
    result = check_fixture(document, fixture)
    assert expected_code in _result_codes(result)
    assert result.passed is False


def test_skeleton_and_shell_objects_do_not_pass():
    document = _make_document()

    skeleton = ChapterFixture.model_validate(
        _fixture_payload(
            "fixture:objectives:skeleton",
            "contract:v2-n-3-1-1:v2",
            "skeleton",
            {"facts": [], "claims": [], "evidence": [], "objects": []},
        )
    )
    result = check_fixture(document, skeleton)
    codes = _result_codes(result)
    assert result.passed is False
    assert "skeleton_content" in codes
    assert "missing_required_claim" in codes
    assert "missing_required_fact" in codes
    assert "missing_structural_object" in codes

    # Object shells with declared ids/occurrences but no real content fail.
    shell = _objectives_positive_content()
    shell["objects"] = [
        {"object_kind": "paragraph", "occurrences": 2, "text": None},
        {
            "object_kind": "table",
            "occurrences": 1,
            "cells": [{"cell_id": "estimand:table:primary_endpoint", "value": None}],
        },
    ]
    shell["claims"] = [{"claim_type": "study_objective", "statement": "有实质声明。"}]
    shell["facts"] = [{"fact_path": "picos.objective.primary", "value": "事实值。"}]
    shell["evidence"] = _objectives_positive_content()["evidence"]
    fixture = ChapterFixture.model_validate(
        _fixture_payload(
            "fixture:objectives:shell",
            "contract:v2-n-3-1-1:v2",
            "skeleton",
            shell,
        )
    )
    result = check_fixture(document, fixture)
    codes = _result_codes(result)
    assert result.passed is False
    assert "missing_structural_object" in codes
    assert "missing_required_cell" in codes


def test_forbidden_fact_and_claim_presence_fails():
    document = _make_document()
    content = _objectives_positive_content()
    content["claims"].append(
        {"claim_type": "marketing_claim", "statement": "本品疗效卓越，值得信赖。"}
    )
    content["facts"].append(
        {"fact_path": "glossary.term_count", "value": "27"}
    )
    fixture = ChapterFixture.model_validate(
        _fixture_payload(
            "fixture:objectives:forbidden",
            "contract:v2-n-3-1-1:v2",
            "positive",
            content,
        )
    )
    result = check_fixture(document, fixture)
    assert "forbidden_claim_present" in _result_codes(result)
    assert result.passed is False


def test_supplied_passed_and_qc_verdict_are_never_trusted():
    document = _make_document()
    fixture = ChapterFixture.model_validate(
        _fixture_payload(
            "fixture:objectives:skeleton",
            "contract:v2-n-3-1-1:v2",
            "skeleton",
            {"facts": [], "claims": [], "evidence": [], "objects": []},
            supplied_passed=True,
            supplied_qc_verdict="QC PASSED: 医学审核通过",
        )
    )
    result = check_fixture(document, fixture)
    assert result.passed is False
    assert result.ignored_supplied_verdict is True
    assert _result_codes(result)


def test_control_provenance_fixture_passes_without_medical_claims():
    document = _make_document()
    positive = ChapterFixture.model_validate(
        _fixture_payload(
            "fixture:cover:positive",
            "contract:v2-front-block:v2",
            "positive",
            _cover_positive_content(),
        )
    )
    result = check_fixture(document, positive)
    assert result.passed is True
    assert not _result_codes(result)
    # Provenance pass must not read as a medical pass.
    assert any(
        "medical_and_qc_judgment_not_executed" in item
        for item in result.deferred_qc_obligations
    )

    missing = ChapterFixture.model_validate(
        _fixture_payload(
            "fixture:cover:missing-control",
            "contract:v2-front-block:v2",
            "missing_control",
            {"facts": [], "objects": []},
        )
    )
    result = check_fixture(document, missing)
    assert result.passed is False
    assert "missing_required_fact" in _result_codes(result)
    assert "missing_required_cell" in _result_codes(result)


def test_skill_output_is_checked_by_same_engine():
    document = _make_document()
    good = ChapterSkillOutput(
        chapter_contract_id="contract:v2-n-3-1-1:v2",
        node_id="v2_n_3_1_1",
        facts=[{"fact_path": "picos.objective.primary", "value": "已确认事实。"}],
        claims=[{"claim_type": "study_objective", "statement": "主要目的声明。"}],
        evidence=[
            {
                "source_role": "regulatory_or_guideline",
                "admission_claim_type": "study_objective",
                "locator_kind": "table",
                "locator": "指南表 3",
                "context": "指南表 3 上下文。",
                "quality_score": 0.9,
            }
        ],
        objects=[
            {"object_kind": "paragraph", "occurrences": 2, "text": "正文段落。"},
            {
                "object_kind": "table",
                "occurrences": 1,
                "cells": [
                    {"cell_id": "estimand:table:primary_endpoint", "value": "12 周缓解率"}
                ],
            },
        ],
    )
    result = check_skill_output(document, good)
    assert result.passed is True
    assert not _result_codes(result)

    empty_self_report = ChapterSkillOutput(
        chapter_contract_id="contract:v2-n-3-1-1:v2",
        node_id="v2_n_3_1_1",
        self_reported_passed=True,
        self_reported_qc_verdict="PASS",
    )
    result = check_skill_output(document, empty_self_report)
    assert result.passed is False
    assert result.ignored_supplied_verdict is True


# ---------------------------------------------------------------------------
# Linter: synthetic template (full mode) and the real accepted template.
# ---------------------------------------------------------------------------


SYN_TEMPLATE_ID = "syn_tp_v1"
SYN_SHA = "b" * 64


def _synthetic_template_dir(tmp_path: Path) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    node = {
        "id": "",
        "level": 0,
        "parent_id": "",
        "is_leaf": True,
        "is_leaf_heading": True,
        "title_zh": "",
        "section_number": "",
    }
    nodes = []
    for index, node_id in enumerate(("syn_n_1", "syn_n_2")):
        entry = copy.deepcopy(node)
        entry["id"] = node_id
        entry["title_zh"] = f"合成章 {index + 1}"
        entry["section_number"] = str(index + 1)
        nodes.append(entry)
    (tmp_path / "node_tree.json").write_text(
        json.dumps(
            {
                "heading_style_tree": {"leaf_count": 2, "node_count": 2, "nodes": nodes},
                "outlined_tree": {"leaf_count": 2, "node_count": 2, "nodes": nodes},
                "front_block": {
                    "body_child_index_range": [0, 3],
                    "content_paragraph_indexes": [0, 1],
                    "note": "合成无标题前置块。",
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (tmp_path / "template.json").write_text(
        json.dumps(
            {
                "template_id": SYN_TEMPLATE_ID,
                "source": {"sha256": SYN_SHA},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return tmp_path


def _syn_chapter(index: int, **contract_overrides) -> ChapterContractV2:
    node_id = f"syn_n_{index}"
    payload = {
        "chapter_contract_id": f"contract:syn-{index}:v2",
        "semantic_node_id": node_id,
        "contract_version": "1.0.0",
        "template_id": SYN_TEMPLATE_ID,
        "template_sha256": SYN_SHA,
        "chapter_skill_id": f"skill:chapter:syn-{index}",
        "chapter_skill_version": "1.0.0",
        "substantive_content": {
            "substantive_content_contract_id": f"content:syn-{index}:v2",
            "chapter_contract_id": f"contract:syn-{index}:v2",
            "fact_requirements": (
                {
                    "fact_path": "provenance.template.version",
                    "obligation": "required",
                    "rationale": "合成章绑定模板版本 provenance。",
                },
            ),
            "structural_object_obligations": (
                {
                    "object_kind": "paragraph",
                    "minimum_occurrences": 1,
                    "project_specific_specification": f"合成章 {index} 的项目化正文义务。",
                },
            ),
            "project_specific_elements": (f"合成章 {index} 项目义务",),
            "skeleton_risk_rules": ("只有标题即失败",),
        },
        "word_rules": {
            "word_formatting_rules_id": f"word:rules:syn-{index}",
            "required_styles": ("Heading 2",),
        },
        "positive_qc_rules": (
            {
                "positive_qc_rule_id": f"qc:syn-{index}:body",
                "rule": f"合成章 {index} 必须给出项目化正文。",
            },
        ),
    }
    payload.update(contract_overrides)
    return ChapterContractV2.model_validate(payload)


def _syn_entry(
    contract: ChapterContractV2, coverage_role: str = "heading_leaf", **overrides
) -> dict:
    return _entry_payload(contract, coverage_role, **overrides)


def _syn_registry_payload(entries: list[dict], fixtures: list[dict] | None = None) -> dict:
    payload = _registry_payload(entries, fixtures)
    payload["template_id"] = SYN_TEMPLATE_ID
    payload["template_sha256"] = SYN_SHA
    return payload


def _syn_cover_contract(**overrides) -> ChapterContractV2:
    payload = json.loads(_cover_contract().model_dump_json())
    payload.update(
        {
            "template_id": SYN_TEMPLATE_ID,
            "template_sha256": SYN_SHA,
        }
    )
    payload.update(overrides)
    return ChapterContractV2.model_validate(payload)


def _with_complete_fixture_families(payload):
    """Supply actual exercised control fixtures for full-mode synthetic tests.

    Synthetic project-control evidence is intentionally not medical evidence.
    Existing fixture rows are retained; their positive evidence is populated.
    """
    payload = copy.deepcopy(payload)
    payload["claim_vocabulary"].append("synthetic_document_control")
    for entry in payload["chapters"]:
        contract = entry["contract"]
        substantive = contract["substantive_content"]
        substantive["evidence_source_requirements"] = [{
            "source_roles": ["project_primary"],
            "admission_claim_types": ["synthetic_document_control"],
            "allowed_locator_kinds": ["body"], "require_context_window": True,
            "minimum_quality_score": 0.8,
        }]
        evidence = [{
            "source_role": "project_primary", "admission_claim_type": "synthetic_document_control",
            "locator_kind": "body", "locator": "Synthetic control register, version section",
            "context": "Synthetic test record, not a real approval or clinical source.",
            "quality_score": 1.0,
        }]
        positive = {
            "facts": [{"fact_path": item["fact_path"], "value": "Synthetic document version"}
                      for item in substantive["fact_requirements"] if item["obligation"] == "required"],
            "evidence": evidence,
            "objects": [{"object_kind": item["object_kind"],
                         "occurrences": item["minimum_occurrences"],
                         "text": "Synthetic document-control content",
                         "cells": [{"cell_id": cell, "value": "Synthetic version cell"}
                                   for cell in item.get("required_object_cells", [])]}
                        for item in substantive["structural_object_obligations"]],
        }
        for fixture in payload["fixtures"]:
            if fixture["chapter_contract_id"] == contract["chapter_contract_id"] and fixture["fixture_kind"] == "positive":
                fixture["content"]["evidence"] = copy.deepcopy(evidence)
        missing = copy.deepcopy(positive)
        missing["facts"] = []
        wrong = copy.deepcopy(positive)
        wrong["evidence"][0]["source_role"] = "company_style_only"
        for kind, content in (("positive", positive), ("missing_control", missing),
                              ("wrong_source", wrong), ("skeleton", {})):
            payload["fixtures"].append(_fixture_payload(
                f"fixture:complete:{entry['node_id']}:{kind}",
                contract["chapter_contract_id"], kind, content,
            ))
    return payload


def test_full_mode_complete_registry_reports_complete(tmp_path):
    template_dir = _synthetic_template_dir(tmp_path / "template")
    cover = _syn_cover_contract()
    one = _syn_chapter(1)
    two = _syn_chapter(
        2,
        dependency_ids=("contract:syn-1:v2",),
        dependency_repair_policy={
            "dependency_repair_policy_id": "repair:syn-2:policy",
            "dependency_ids": ("contract:syn-1:v2",),
            "downstream_impact": "上游合成章修订后本章必须同步修订。",
            "repair_owner": "ai",
            "max_repair_attempts": 2,
            "repair_steps": (
                {
                    "repair_step_id": "repair:syn-2:step-1",
                    "sequence": 1,
                    "action": "重读上游差异并重算引用。",
                    "owner": "ai",
                },
            ),
        },
    )
    entries = [
        _entry_payload(cover, "cover"),
        _entry_payload(one, "heading_leaf"),
        _entry_payload(two, "heading_leaf"),
    ]
    document = load_chapter_registry(_with_complete_fixture_families(_syn_registry_payload(entries)))
    report = lint_registry(template_dir, document, require_complete=True)
    assert report.mode == "full"
    assert report.status == "complete"
    assert report.errors() == ()
    assert report.coverage.leaf_union_count == 2
    assert report.coverage.expected_carrier_count == 3
    assert report.coverage.covered_carrier_count == 3
    assert report.coverage.missing_node_ids == ()
    assert report.coverage.cover_node_id == "v2_front_block"


def test_full_mode_missing_coverage_lists_nodes_and_fails(tmp_path):
    template_dir = _synthetic_template_dir(tmp_path / "template")
    cover = _syn_cover_contract()
    one = _syn_chapter(1)
    document = load_chapter_registry(
        _syn_registry_payload([_entry_payload(cover, "cover"), _entry_payload(one)])
    )
    report = lint_registry(template_dir, document, require_complete=True)
    assert report.status == "incomplete"
    assert "syn_n_2" in report.coverage.missing_node_ids
    missing = [f for f in report.errors() if f.code == "missing_coverage"]
    assert any(f.node_id == "syn_n_2" for f in missing)


def test_partial_mode_reports_incomplete_and_never_complete(tmp_path):
    template_dir = _synthetic_template_dir(tmp_path / "template")
    cover = _syn_cover_contract()
    document = load_chapter_registry(_syn_registry_payload([_entry_payload(cover, "cover")]))
    report = lint_registry(template_dir, document, require_complete=False)
    assert report.mode == "partial"
    # Partial mode never represents full acceptance, even in findings.
    assert report.status == "incomplete"
    codes = {f.code for f in report.findings}
    assert "partial_mode_not_full_acceptance" in codes
    # Missing carriers are enumerated without blocking batch validation.
    error_codes = {f.code for f in report.errors()}
    assert "missing_coverage" not in error_codes
    assert "syn_n_1" in report.coverage.missing_node_ids


def test_unexpected_carrier_and_role_mismatch_fail(tmp_path):
    template_dir = _synthetic_template_dir(tmp_path / "template")
    cover = _syn_cover_contract()
    one = _syn_chapter(1)
    two = _syn_chapter(2)
    # A carrier on a node outside the leaf union ∪ cover is unexpected.
    ghost = _syn_chapter(3, semantic_node_id="syn_n_heading_container")
    entries = [
        _entry_payload(cover, "cover"),
        _entry_payload(one),
        _entry_payload(two),
        _entry_payload(ghost, "heading_leaf"),
    ]
    document = load_chapter_registry(_syn_registry_payload(entries))
    report = lint_registry(template_dir, document, require_complete=True)
    codes = {f.code for f in report.errors()}
    assert "unexpected_carrier" in codes

    # Wrong coverage role for the node's leaf status.
    entries = [
        _entry_payload(cover, "cover"),
        _entry_payload(one, "outline_only_leaf"),
        _entry_payload(two),
    ]
    document = load_chapter_registry(_syn_registry_payload(entries))
    report = lint_registry(template_dir, document, require_complete=True)
    assert "coverage_role_mismatch" in {f.code for f in report.errors()}


def test_unknown_vocabulary_entries_fail(tmp_path):
    template_dir = _synthetic_template_dir(tmp_path / "template")
    cover = _syn_cover_contract()
    one = _syn_chapter(
        1,
        substantive_content={
            "substantive_content_contract_id": "content:syn-1:v2",
            "chapter_contract_id": "contract:syn-1:v2",
            "fact_requirements": (
                {
                    "fact_path": "synthetic.fact.not_in_vocabulary",
                    "obligation": "required",
                    "rationale": "词表外的路径必须被交叉检查拒绝。",
                },
            ),
            "skeleton_risk_rules": ("只有标题即失败",),
        },
    )
    document = load_chapter_registry(
        _registry_payload_from_syn([_entry_payload(cover, "cover"), _entry_payload(one)])
    )
    report = lint_registry(template_dir, document, require_complete=True)
    assert "unknown_fact_path" in {f.code for f in report.errors()}

    one = _syn_chapter(
        2,
        substantive_content={
            "substantive_content_contract_id": "content:syn-2:v2",
            "chapter_contract_id": "contract:syn-2:v2",
            "claim_requirements": (
                {
                    "claim_type": "unknown_claim_type",
                    "obligation": "required",
                    "rationale": "词表外的声明必须被拒绝。",
                },
            ),
            "skeleton_risk_rules": ("只有标题即失败",),
        },
    )
    document = load_chapter_registry(
        _registry_payload_from_syn([_entry_payload(cover, "cover"), _entry_payload(one)])
    )
    report = lint_registry(template_dir, document, require_complete=True)
    assert "unknown_claim_type" in {f.code for f in report.errors()}


def _registry_payload_from_syn(entries: list[dict]) -> dict:
    return _syn_registry_payload(entries)


def test_conditional_required_vs_forbidden_conflict_fails(tmp_path):
    template_dir = _synthetic_template_dir(tmp_path / "template")
    cover = _syn_cover_contract()
    one = _syn_chapter(1)
    payload = json.loads(one.model_dump_json())
    payload["substantive_content"]["fact_requirements"] = list(
        payload["substantive_content"]["fact_requirements"]
    ) + [
        {
            "fact_path": "synthetic.legacy.fact",
            "obligation": "forbidden",
            "rationale": "已废弃事实，禁止引用。",
        }
    ]
    payload["conditional_applicability_rules"] = [
        {
            "conditional_applicability_rule_id": "applicability:syn-conflict",
            "triggering_fact_paths": ("provenance.template.version",),
            "condition": "合成条件",
            "rationale": "条件激活时要求已废弃事实，构成矛盾。",
            "required_when_active_fact_paths": ("synthetic.legacy.fact",),
        }
    ]
    conflicted = ChapterContractV2.model_validate(payload)
    document = load_chapter_registry(
        _syn_registry_payload([_entry_payload(cover, "cover"), _entry_payload(conflicted)])
    )
    report = lint_registry(template_dir, document, require_complete=True)
    assert "conditional_forbidden_conflict" in {f.code for f in report.errors()}


def test_dangling_ctq_anchor_fails(tmp_path):
    template_dir = _synthetic_template_dir(tmp_path / "template")
    cover = _syn_cover_contract()
    one = _syn_chapter(1)
    payload = json.loads(one.model_dump_json())
    payload["ctq_items"] = [
        {
            "ctq_item_id": "ctq:syn-dangling",
            "question": "该 CtQ 锚定到未声明的事实路径。",
            "linked_fact_paths": ("synthetic.undeclared.fact",),
            "risk_if_unmet": "无法核查。",
        }
    ]
    dangling = ChapterContractV2.model_validate(payload)
    document = load_chapter_registry(
        _syn_registry_payload([_entry_payload(cover, "cover"), _entry_payload(dangling)])
    )
    report = lint_registry(template_dir, document, require_complete=True)
    assert "dangling_ctq_anchor" in {f.code for f in report.errors()}


def test_dangling_dependency_full_error_partial_warning(tmp_path):
    template_dir = _synthetic_template_dir(tmp_path / "template")
    cover = _syn_cover_contract()
    one = _syn_chapter(1)
    two = _syn_chapter(
        2,
        dependency_ids=("contract:ghost:v2",),
        dependency_repair_policy={
            "dependency_repair_policy_id": "repair:syn-2:policy",
            "dependency_ids": ("contract:ghost:v2",),
            "downstream_impact": "幽灵依赖。",
            "repair_owner": "ai",
            "max_repair_attempts": 2,
            "repair_steps": (
                {
                    "repair_step_id": "repair:syn-2:step-1",
                    "sequence": 1,
                    "action": "核查依赖。",
                    "owner": "ai",
                },
            ),
        },
    )
    document = load_chapter_registry(
        _syn_registry_payload([_entry_payload(cover, "cover"), _entry_payload(two)])
    )
    full = lint_registry(template_dir, document, require_complete=True)
    assert "dangling_dependency" in {f.code for f in full.errors()}
    partial = lint_registry(template_dir, document, require_complete=False)
    assert "dangling_dependency" in {f.code for f in partial.findings}
    assert not ({"dangling_dependency"} & {f.code for f in partial.errors()})


def test_template_hash_and_id_mismatch_fail(tmp_path):
    """An internally consistent registry bound to the wrong template identity
    loads, then the linter reports the mismatch against template.json.
    (A registry internally split across two template identities fails closed
    at load instead.)"""

    template_dir = _synthetic_template_dir(tmp_path / "template")
    payload = _syn_registry_payload(
        [
            _entry_payload(_syn_cover_contract(), "cover"),
            _entry_payload(_syn_chapter(1)),
            _entry_payload(_syn_chapter(2)),
        ]
    )
    payload["template_sha256"] = "c" * 64
    for entry in payload["chapters"]:
        entry["contract"]["template_sha256"] = "c" * 64
        for skill in entry["skills"]:
            skill["template_sha256"] = "c" * 64
    document = load_chapter_registry(payload)
    report = lint_registry(template_dir, document, require_complete=True)
    assert "template_hash_mismatch" in {f.code for f in report.errors()}

    payload = _syn_registry_payload(
        [
            _entry_payload(_syn_cover_contract(), "cover"),
            _entry_payload(_syn_chapter(2)),
        ]
    )
    payload["template_id"] = "other_template"
    for entry in payload["chapters"]:
        entry["contract"]["template_id"] = "other_template"
        for skill in entry["skills"]:
            skill["template_id"] = "other_template"
    document = load_chapter_registry(payload)
    report = lint_registry(template_dir, document, require_complete=True)
    assert "template_id_mismatch" in {f.code for f in report.errors()}


def test_skill_not_bound_fails(tmp_path):
    template_dir = _synthetic_template_dir(tmp_path / "template")
    cover = _syn_cover_contract()
    one = _syn_chapter(1)
    entry = _entry_payload(one)
    entry["skills"][0]["skill_id"] = "skill:chapter:unbound"
    document = load_chapter_registry(
        _syn_registry_payload([_entry_payload(cover, "cover"), entry])
    )
    report = lint_registry(template_dir, document, require_complete=True)
    assert "skill_not_bound" in {f.code for f in report.errors()}


def test_missing_or_duplicate_cover_carrier_fails(tmp_path):
    template_dir = _synthetic_template_dir(tmp_path / "template")
    one = _syn_chapter(1)
    two = _syn_chapter(2)
    document = load_chapter_registry(
        _syn_registry_payload([_entry_payload(one), _entry_payload(two)])
    )
    report = lint_registry(template_dir, document, require_complete=True)
    codes = {f.code for f in report.errors()}
    assert "missing_cover_carrier" in codes

    cover = _syn_cover_contract()
    duplicate = _syn_cover_contract(
        chapter_contract_id="contract:syn-dup-cover:v2",
        substantive_content={
            "substantive_content_contract_id": "content:syn-dup-cover:v2",
            "chapter_contract_id": "contract:syn-dup-cover:v2",
            "fact_requirements": (
                {
                    "fact_path": "provenance.template.version",
                    "obligation": "required",
                    "rationale": "重复封面对照合同。",
                },
            ),
            "project_specific_elements": ("重复封面对照",),
            "skeleton_risk_rules": ("只有标题即失败",),
        },
        semantic_node_id="syn_n_1",
        chapter_skill_id="skill:chapter:syn-dup-cover",
    )
    duplicate_entry = _entry_payload(duplicate, "cover")
    duplicate_entry["node_id"] = "syn_n_1"
    document = load_chapter_registry(
        _syn_registry_payload(
            [
                _entry_payload(cover, "cover"),
                duplicate_entry,
                _entry_payload(_syn_chapter(2)),
            ]
        )
    )
    report = lint_registry(template_dir, document, require_complete=True)
    codes = {f.code for f in report.errors()}
    assert "duplicate_cover_carrier" in codes or "unexpected_carrier" in codes


def test_real_template_derives_leaf_union_and_partial_batch(tmp_path):
    """Real accepted template: 106 heading leaves ∪ 109 outline leaves = 110,
    plus the unheaded cover carrier.  Counts are derived, never hardcoded."""

    node_tree = json.loads(
        (REAL_TEMPLATE_DIR / "node_tree.json").read_text(encoding="utf-8")
    )
    heading_leaves = {
        n["id"] for n in node_tree["heading_style_tree"]["nodes"] if n.get("is_leaf_heading")
    }
    outline_leaves = {
        n["id"] for n in node_tree["outlined_tree"]["nodes"] if n.get("is_leaf")
    }
    leaf_union = heading_leaves | outline_leaves
    assert len(heading_leaves) == 106
    assert len(outline_leaves) == 109
    assert len(leaf_union) == 110
    assert heading_leaves - outline_leaves == {"v2_n_16"}
    assert outline_leaves - heading_leaves == {
        "v2_n_16_x1",
        "v2_n_16_x2",
        "v2_n_16_x3",
        "v2_n_front_5",
    }

    entries = [
        _entry_payload(_cover_contract(), "cover"),
        _entry_payload(_objectives_contract(), "heading_leaf"),
        _entry_payload(_aggregation_contract(), "heading_only_aggregation"),
        _entry_payload(_glossary_contract(), "outline_only_leaf"),
    ]
    document = load_chapter_registry(_registry_payload(entries))

    # Partial batch against the real template: enumerated, never complete.
    partial = lint_registry(REAL_TEMPLATE_DIR, document, require_complete=False)
    assert partial.mode == "partial"
    assert partial.status == "incomplete"
    assert partial.coverage.leaf_union_count == len(leaf_union)
    assert partial.coverage.expected_carrier_count == len(leaf_union) + 1
    assert partial.coverage.covered_carrier_count == 4
    assert len(partial.coverage.missing_node_ids) == len(leaf_union) + 1 - 4
    assert "v2_n_3_2_1" in partial.coverage.missing_node_ids
    assert "partial_mode_not_full_acceptance" in {f.code for f in partial.findings}

    # Full mode reports the same gaps as blocking errors.
    full = lint_registry(REAL_TEMPLATE_DIR, document, require_complete=True)
    assert full.status == "incomplete"
    missing = [f for f in full.errors() if f.code == "missing_coverage"]
    assert len(missing) == len(leaf_union) + 1 - 4
    assert not any(f.node_id == "v2_n_3_1_1" for f in missing)

    # The appendix container is aggregation; the concrete appendix leaf and the
    # glossary leaf are outline-only carriers; a swap is a role mismatch.
    swapped = json.loads(json.dumps(_registry_payload(entries), ensure_ascii=False))
    for entry in swapped["chapters"]:
        if entry["node_id"] == "v2_n_16":
            entry["coverage_role"] = "heading_leaf"
    swapped_document = load_chapter_registry(swapped)
    report = lint_registry(REAL_TEMPLATE_DIR, swapped_document, require_complete=False)
    role_errors = [
        f for f in report.errors() if f.code == "coverage_role_mismatch"
    ]
    assert any(f.node_id == "v2_n_16" for f in role_errors)


# ---------------------------------------------------------------------------
# CLI: read-only, JSON/text output, exit status.
# ---------------------------------------------------------------------------


def _cli_env() -> dict:
    return {
        "PATH": "/usr/bin:/bin",
        "HOME": os.environ.get("HOME", "/tmp"),
        "LANG": "en_US.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "PYTHONPATH": "tests/protocol_v3:services/api:packages:.",
        "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
    }


def _run_cli(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "scripts/qc/protocol_v3/lint_chapter_registry.py", *args],
        cwd=str(cwd),
        env=_cli_env(),
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_cli_exit_codes_json_output_and_readonly(tmp_path):
    template_dir = _synthetic_template_dir(tmp_path / "template")
    registry_path = tmp_path / "syn_registry.json"

    cover = _syn_cover_contract()
    one = _syn_chapter(1)
    two = _syn_chapter(2)
    complete = _syn_registry_payload(
        [
            _entry_payload(cover, "cover"),
            _entry_payload(one),
            _entry_payload(two),
        ],
        fixtures=[
            _fixture_payload(
                "fixture:syn-1:positive",
                "contract:syn-1:v2",
                "positive",
                {
                    "facts": [
                        {"fact_path": "provenance.template.version", "value": "v1"}
                    ],
                    "objects": [
                        {"object_kind": "paragraph", "occurrences": 1, "text": "正文。"}
                    ],
                },
            ),
        ],
    )
    complete = _with_complete_fixture_families(complete)
    registry_path.write_text(json.dumps(complete, ensure_ascii=False), encoding="utf-8")
    before = sorted(p.name for p in tmp_path.iterdir())

    result = _run_cli(
        [
            "--registry",
            str(registry_path),
            "--template-dir",
            str(template_dir),
            "--json",
            "--check-fixtures",
        ],
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["status"] == "complete"
    assert report["mode"] == "full"
    assert report["fixture_results"][0]["passed"] is True

    # Incomplete registry in full mode: exit 1 with missing coverage.
    incomplete = _syn_registry_payload(
        [_entry_payload(cover, "cover"), _entry_payload(one)]
    )
    registry_path.write_text(
        json.dumps(incomplete, ensure_ascii=False), encoding="utf-8"
    )
    result = _run_cli(
        ["--registry", str(registry_path), "--template-dir", str(template_dir)],
        cwd=REPO_ROOT,
    )
    assert result.returncode == 1
    assert "missing_coverage" in result.stdout
    assert "syn_n_2" in result.stdout

    # Partial mode: batch validates but the output says incomplete, exit 0.
    result = _run_cli(
        [
            "--registry",
            str(registry_path),
            "--template-dir",
            str(template_dir),
            "--partial",
        ],
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0
    assert "incomplete" in result.stdout

    # Usage/IO failure: exit 2 without traceback noise.
    result = _run_cli(
        ["--registry", str(tmp_path / "missing.json"), "--template-dir", str(template_dir)],
        cwd=REPO_ROOT,
    )
    assert result.returncode == 2

    # Read-only: no source mutations or stray files.
    after = sorted(p.name for p in tmp_path.iterdir())
    assert before == after
