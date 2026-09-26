from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import fitz
import pytest


SLICE = (
    Path(__file__).resolve().parents[1]
    / "records"
    / "active_slices"
    / "medical_writing_phase1_autoimmune_mnc_corpus_20260716"
)

# The slice holds user-local corpus working records and is intentionally not
# version-controlled; the source-boundary contracts below only apply when the
# slice is present on the machine.
pytestmark = pytest.mark.skipif(
    not SLICE.is_dir(),
    reason="local phase1 corpus slice (records/active_slices/...) absent from this checkout",
)


def load_script(name: str):
    path = SLICE / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"phase1_corpus_{name}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_primary_protocol_selection_excludes_amendment_summary(tmp_path, monkeypatch):
    selector = load_script("build_translation_selection")
    receipt_dir = tmp_path / "receipts"
    receipt_dir.mkdir()
    receipt = {
        "documents": [
            {
                "filename": "Prot_002.pdf",
                "type_abbrev": "Prot",
                "label": "Study Protocol: Amendment Summary of Changes",
                "bytes": 9_000,
            },
            {
                "filename": "Prot_001.pdf",
                "type_abbrev": "Prot",
                "label": "Study Protocol: Clinical Study Protocol",
                "bytes": 5_000,
            },
        ]
    }
    (receipt_dir / "NCT00000000.json").write_text(json.dumps(receipt), encoding="utf-8")
    monkeypatch.setattr(selector, "ROOT", tmp_path)

    selected = selector.primary_protocol_metadata("NCT00000000")

    assert selected["filename"] == "Prot_001.pdf"


def test_validator_rejects_locator_page_without_source_overlap(tmp_path, monkeypatch):
    validator = load_script("validate_translation_selection")
    document_path = tmp_path / "raw" / "documents" / "NCT00000000" / "Prot_001.pdf"
    document_path.parent.mkdir(parents=True)
    source = (
        "This randomized clinical pharmacology study uses a fixed sequence design with a seven day washout. "
        "Eligible participants receive one oral dose after an overnight fast and complete serial pharmacokinetic sampling. "
        "The safety review committee evaluates all available tolerability data before the next cohort starts."
    )
    document = fitz.open()
    page_one = document.new_page()
    page_one.insert_textbox(fitz.Rect(40, 40, 550, 760), source, fontsize=10)
    page_two = document.new_page()
    page_two.insert_textbox(
        fitz.Rect(40, 40, 550, 760),
        "A completely unrelated appendix lists archive contacts and document-control signatures.",
        fontsize=10,
    )
    document.save(document_path)
    document.close()

    selection_path = tmp_path / "translations" / "translation_selection.json"
    selection_path.parent.mkdir()
    selection_path.write_text(
        json.dumps(
            [
                {
                    "segment_id": "phase1_locator_regression",
                    "nct_id": "NCT00000000",
                    "source_file": "raw/documents/NCT00000000/Prot_001.pdf",
                    "source_locator": "Protocol test, PDF pages 1-2",
                    "source_text": source,
                    "source_text_sha256": hashlib.sha256(source.encode()).hexdigest(),
                    "document_sha256": hashlib.sha256(document_path.read_bytes()).hexdigest(),
                }
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "reports").mkdir()
    monkeypatch.setattr(validator, "ROOT", tmp_path)
    monkeypatch.setattr(validator, "SELECTION", selection_path)

    with pytest.raises(SystemExit, match="locator pages do not contribute source text: \\[2\\]"):
        validator.main()


def test_executor_candidate_packet_is_complete_current_and_hash_bound():
    builder = load_script("build_executor_candidate_packet")

    packet = builder.build_packet()

    assert packet["schema_version"] == "phase1_executor_candidate_packet_v1"
    assert len(packet["records"]) == 12
    assert not builder.SUPERSEDED_IDS.intersection(
        record["segment_id"] for record in packet["records"]
    )
    for record in packet["records"]:
        assert hashlib.sha256(record["literal_candidate"].encode()).hexdigest() == record[
            "literal_candidate_sha256"
        ]
        assert hashlib.sha256(record["humanizer_candidate"].encode()).hexdigest() == record[
            "humanizer_candidate_sha256"
        ]
        if record["segment_id"].startswith("phase1_nct02352493"):
            assert record["selection_status"] == "hold_translation_pending"
            assert record["corpus_tier"] == "phase1_2_boundary_exception"


def test_production_runner_requires_explicit_boundary_opt_in():
    runner = load_script("run_production_translations")
    selections = json.loads((SLICE / "translations" / "translation_selection.json").read_text())
    held_id = next(
        item["segment_id"]
        for item in selections
        if item["selection_status"] == "hold_translation_pending"
    )

    default_eligible = runner.eligible_selections(
        selections, include_boundary=False, only_segments=set()
    )
    assert all(
        item["selection_status"] != "hold_translation_pending" for item in default_eligible
    )
    with pytest.raises(ValueError, match="explicit --include-boundary"):
        runner.eligible_selections(
            selections, include_boundary=False, only_segments={held_id}
        )
    opted_in = runner.eligible_selections(
        selections, include_boundary=True, only_segments={held_id}
    )
    assert [item["segment_id"] for item in opted_in] == [held_id]


def test_finalization_instruction_carries_both_untrusted_candidates():
    runner = load_script("run_production_translations")
    candidate = {
        "literal_candidate": "直译候选，阈值 >1.5 倍。",
        "humanizer_candidate": "润色候选，阈值超过1.5倍。",
    }

    instruction = runner.finalization_instruction(candidate)

    assert isinstance(instruction, str)
    assert candidate["literal_candidate"] in instruction
    assert candidate["humanizer_candidate"] in instruction
    assert "不得把 > 改为 ≥" in instruction
    assert "非权威执行模型草稿" in instruction


def test_flash_translation_contract_is_distinct_from_pro_contract():
    runner = load_script("run_production_translations")

    flash_hash = runner.translation_contract_hash("deepseek-v4-flash")
    pro_hash = runner.translation_contract_hash("deepseek-v4-pro")

    assert len(flash_hash) == 64
    assert len(pro_hash) == 64
    assert flash_hash != pro_hash


def test_biologic_selection_reuses_current_translation_contract():
    builder = load_script("build_biologic_translation_selection")

    selections = builder.build()

    assert len(selections) == 8
    assert len({item["segment_id"] for item in selections}) == 8
    assert {item["corpus_tier"] for item in selections} == {
        "core_phase1_autoimmune_biologic"
    }
    assert all(item["selection_status"] == "translation_pending" for item in selections)
    assert all(len(item["document_sha256"]) == 64 for item in selections)
    assert all(len(item["source_text_sha256"]) == 64 for item in selections)
    assert all(
        item["source_url"].endswith(Path(item["source_file"]).name)
        for item in selections
    )
    assert {item["modality"] for item in selections} >= {
        "monoclonal_antibody",
        "engineered_biologic",
        "bispecific_fusion_protein",
    }


def test_flash_correction_instruction_is_source_authority_and_quality_specific():
    runner = load_script("run_production_translations")
    instruction = runner.source_correction_instruction(
        {
            "translated_text": "应指导患者不要漏服；从150mg减至100mg。",
            "fidelity_failure_codes": [
                "regulatory_chinese_term_calque",
                "unit_spacing_changed",
            ],
        },
        "IR tablets and PK samples are evaluated for DDI.",
    )

    assert "不是证据" in instruction
    assert "H2受体拮抗剂" in instruction
    assert "研究中心访视" in instruction
    assert "应指导患者不得漏服" in instruction
    assert "150 mg" in instruction
    assert '["DDI","IR","PK"]' in instruction
