from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "scripts" / "qc" / "d017_competitor_triage_v5_acceptance.py"
SPEC = importlib.util.spec_from_file_location("d017_triage_v5_qc", TOOL_PATH)
assert SPEC is not None and SPEC.loader is not None
qc = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(qc)


def _candidate(index: int) -> dict:
    nct_id = f"NCT{index:08d}"
    return {
        "nct_id": nct_id,
        "brief_title": f"PNH pharmacologic study {index}",
        "official_title": (
            "A study in Paroxysmal Nocturnal Hemoglobinuria "
            f"with study drug {index}"
        ),
        "brief_summary": "Study drug in PNH participants.",
        "conditions": ["Paroxysmal Nocturnal Hemoglobinuria"],
        "phases": ["PHASE2"],
        "study_type": "INTERVENTIONAL",
        "interventions": [
            {"name": f"study_drug_{index}", "intervention_type": "DRUG"}
        ],
        "design_allocation": "RANDOMIZED",
        "design_intervention_model": "PARALLEL",
        "design_masking": "DOUBLE",
        "enrollment_count": 100 + index,
        "lead_sponsor": f"Sponsor {index}",
        "overall_status": "COMPLETED",
        "study_record_url": f"https://clinicaltrials.gov/study/{nct_id}",
        "public_documents": [],
    }


def _result(candidate: dict, classification: str = "indirect_reference") -> dict:
    if classification == "indirect_reference":
        reason = (
            "适应症一致（阵发性睡眠性血红蛋白尿症（PNH））。"
            "因当前项目技术类型、给药途径、靶点/机制未知，不能判断直接竞争性，"
            "可作为同适应症药物研究参考。"
        )
    elif classification == "excluded":
        reason = (
            "适应症不同（项目：阵发性睡眠性血红蛋白尿症（PNH）；"
            f"候选：{'、'.join(candidate['conditions'])}）。"
            "因当前项目技术类型、给药途径、靶点/机制未知，不能判断直接竞争性，"
            "不纳入竞品篮子。"
        )
    else:
        reason = "项目与候选三项关键维度均有显式来源，属于直接竞品。"
    return {
        "nct_id": candidate["nct_id"],
        "classification": classification,
        "confidence": 0.8,
        "matching_dimensions": [
            {"dimension": "indication", "match": "match", "detail": "适应症匹配"},
            {"dimension": "phase", "match": "match", "detail": "分期匹配"},
            {
                "dimension": "modality",
                "match": "unknown",
                "detail": "当前项目未提供技术类型信息，不能判断匹配性",
            },
            {
                "dimension": "route",
                "match": "unknown",
                "detail": "当前项目未提供给药途径信息，不能判断匹配性",
            },
            {
                "dimension": "target_mechanism",
                "match": "unknown",
                "detail": "当前项目未提供靶点/机制信息，不能判断匹配性",
            },
            {"dimension": "design", "match": "partial", "detail": "设计可参考"},
        ],
        "document_suitability": {
            "has_public_protocol": False,
            "has_public_sap": False,
            "document_role": "无公开方案或统计分析计划",
        },
        "reason": reason,
        "evidence_gaps": [],
    }


def _valid_pair() -> tuple[dict, dict]:
    candidates = [_candidate(index) for index in range(1, 68)]
    snapshot = {
        "snapshot_id": "wref_search_d017_v5_test",
        "project_id": "proj_d017",
        "request": {
            "indication": "Paroxysmal Nocturnal Hemoglobinuria",
            "phases": ["PHASE2"],
            "study_type": "INTERVENTIONAL",
        },
        "query_url": "https://clinicaltrials.gov/api/v2/studies?query.cond=PNH",
        "api_version": "v2",
        "data_timestamp": "2026-07-24T00:00:00Z",
        "total_count": 67,
        "returned_count": 67,
        "candidates": candidates,
    }
    chunks = []
    boundaries = [(0, 14), (14, 28), (28, 42), (42, 56), (56, 67)]
    for chunk_index, (start, end) in enumerate(boundaries):
        batch = candidates[start:end]
        chunk_id = f"ct_chunk_{chunk_index}"
        chunks.append(
            {
                "chunk_id": chunk_id,
                "chunk_index": chunk_index,
                "nct_ids": [candidate["nct_id"] for candidate in batch],
                "status": "succeeded",
                "results": [_result(candidate) for candidate in batch],
                "provenance": {
                    "provider": qc.EXPECTED_PROVIDER,
                    "response_model": qc.EXPECTED_MODEL,
                    "prompt_version": qc.EXPECTED_PROMPT_VERSION,
                    "schema_version": qc.EXPECTED_SCHEMA_VERSION,
                    "canonical_input_hash": "a" * 64,
                    "canonical_output_hash": "b" * 64,
                },
            }
        )
    run = {
        "run_id": "ct_run_d017_v5_test",
        "project_id": "proj_d017",
        "snapshot_id": snapshot["snapshot_id"],
        "status": "review_ready",
        "prompt_version": qc.EXPECTED_PROMPT_VERSION,
        "schema_version": qc.EXPECTED_SCHEMA_VERSION,
        "provider": qc.EXPECTED_PROVIDER,
        "response_model": qc.EXPECTED_MODEL,
        "snapshot_hash": qc.snapshot_hash(snapshot),
        "chunks": chunks,
    }
    return snapshot, {"run": run}


def _find_result(run_payload: dict, nct_id: str) -> dict:
    for chunk in run_payload["run"]["chunks"]:
        for result in chunk["results"]:
            if result["nct_id"] == nct_id:
                return result
    raise AssertionError(nct_id)


def _refresh_snapshot_hash(snapshot: dict, run_payload: dict) -> None:
    run_payload["run"]["snapshot_hash"] = qc.snapshot_hash(snapshot)


def _issue_codes(report: dict) -> set[str]:
    return {issue["code"] for issue in report["issues"]}


def test_valid_67_candidate_five_chunk_pair_passes():
    snapshot, run_payload = _valid_pair()
    report = qc.build_report(snapshot, run_payload)
    assert report["accepted"] is True
    assert report["summary"]["result_count"] == 67
    assert report["summary"]["chunk_count"] == 5
    assert len(report["source_inventory"]) == 67


def test_v11_gate_uses_semantic_subgroup_prompt_identity():
    assert (
        qc.EXPECTED_PROMPT_VERSION
        == "competitor_triage_deepseek_v13_controlled_condition_qualifiers"
    )


def test_v10_run_and_chunk_prompt_identity_are_rejected_by_v11_gate():
    snapshot, run_payload = _valid_pair()
    run_payload["run"]["prompt_version"] = (
        "competitor_triage_deepseek_v10_crswnp_chronicity"
    )
    for chunk in run_payload["run"]["chunks"]:
        chunk["provenance"]["prompt_version"] = (
            "competitor_triage_deepseek_v10_crswnp_chronicity"
        )

    report = qc.build_report(snapshot, run_payload)

    assert report["accepted"] is False
    assert "run_prompt_version_mismatch" in _issue_codes(report)
    assert "chunk_prompt_version_mismatch" in _issue_codes(report)


@pytest.mark.parametrize(
    ("condition", "expected"),
    [
        ("Paroxysmal Nocturnal Hemoglobinuria", True),
        ("Paroxysmal Hemoglobinuria, Nocturnal", True),
        ("PNH", True),
        ("Paroxysmal Nocturnal Hemoglobinuria (PNH)", True),
        ("PNH - Paroxysmal Nocturnal Hemoglobinuria", True),
        ("Paroxysmal Nocturnal Hemoglobinuria - PNH", True),
        ("Paroxysmal Nocturnal Haemoglobinuria", True),
        (
            "Paroxysmal Nocturnal Hemoglobinuria (PNH) "
            "With Signs of Active Hemolysis",
            True,
        ),
        (
            "Paroxysmal Nocturnal Haemoglobinuria "
            "With Signs of Active Haemolysis",
            True,
        ),
        ("Paroxysmal Nocturnal Dyspnea", False),
        ("PNH - Paroxysmal Nocturnal Dyspnea", False),
        ("Malignant Hematology - PNH", False),
        ("PNH-related Bone Marrow Failure", False),
        ("Paroxysmal Nocturnal Dyspnea (PNH)", False),
        (
            "Paroxysmal Nocturnal Hemoglobinuria and Aplastic Anemia",
            False,
        ),
        (
            "Paroxysmal Nocturnal Hemoglobinuria or Aplastic Anemia",
            False,
        ),
        (
            "Paroxysmal Nocturnal Hemoglobinuria With Active Hemolysis "
            "and Aplastic Anemia",
            False,
        ),
        (
            "Paroxysmal Nocturnal Hemoglobinuria With Active Hemolysis "
            "or Aplastic Anemia",
            False,
        ),
        (
            "Paroxysmal Nocturnal Hemoglobinuria (XYZ) With Active Hemolysis",
            False,
        ),
        (
            "PNH - Paroxysmal Nocturnal Hemoglobinuria - Active Hemolysis",
            False,
        ),
        ("Severe Asthma", False),
    ],
)
def test_indication_matching_is_exact_set_or_proven_abbreviation_only(
    condition: str, expected: bool
):
    assert (
        qc.same_indication(
            [condition],
            project_indication=qc.D017_PROJECT_INDICATION,
            clinicaltrials_condition_term="Paroxysmal Nocturnal Hemoglobinuria",
        )
        is expected
    )


def test_no_subset_or_sixty_percent_overlap():
    assert not qc.same_indication(
        ["Paroxysmal Nocturnal"],
        project_indication=qc.D017_PROJECT_INDICATION,
        clinicaltrials_condition_term="Paroxysmal Nocturnal Hemoglobinuria",
    )


@pytest.mark.parametrize("allowed_type", sorted(qc.PHARMACOLOGIC_TYPES))
def test_each_explicit_permitted_intervention_type_is_pharmacologic(
    allowed_type: str,
):
    candidate = _candidate(1)
    candidate["interventions"] = [
        {"name": "device", "intervention_type": "DEVICE"},
        {"name": "active", "intervention_type": allowed_type},
    ]
    assert qc.has_pharmacologic_intervention(candidate)


def test_mixed_nonpharmacologic_only_is_not_pharmacologic():
    candidate = _candidate(1)
    candidate["interventions"] = [
        {"name": "device", "intervention_type": "DEVICE"},
        {"name": "procedure", "intervention_type": "PROCEDURE"},
        {"name": "behavior", "intervention_type": "BEHAVIORAL"},
    ]
    assert not qc.has_pharmacologic_intervention(candidate)


@pytest.mark.parametrize(
    "condition",
    ["Paroxysmal Nocturnal Dyspnea", "Severe Asthma"],
)
def test_invalid_indirect_condition_is_rejected(condition: str):
    snapshot, run_payload = _valid_pair()
    candidate = snapshot["candidates"][0]
    candidate["conditions"] = [condition]
    _refresh_snapshot_hash(snapshot, run_payload)
    report = qc.build_report(snapshot, run_payload)
    assert report["accepted"] is False
    assert "invalid_indirect_reference" in _issue_codes(report)


def test_indirect_with_only_device_and_procedure_is_rejected():
    snapshot, run_payload = _valid_pair()
    candidate = snapshot["candidates"][0]
    candidate["interventions"] = [
        {"name": "device", "intervention_type": "DEVICE"},
        {"name": "procedure", "intervention_type": "PROCEDURE"},
    ]
    _refresh_snapshot_hash(snapshot, run_payload)
    report = qc.build_report(snapshot, run_payload)
    assert "invalid_indirect_reference" in _issue_codes(report)


def test_indirect_with_mixed_device_and_drug_is_retained():
    snapshot, run_payload = _valid_pair()
    candidate = snapshot["candidates"][0]
    candidate["interventions"] = [
        {"name": "device", "intervention_type": "DEVICE"},
        {"name": "active", "intervention_type": "DRUG"},
    ]
    _refresh_snapshot_hash(snapshot, run_payload)
    report = qc.build_report(snapshot, run_payload)
    assert report["accepted"] is True


def test_direct_is_rejected_when_project_dimensions_are_unknown():
    snapshot, run_payload = _valid_pair()
    candidate = snapshot["candidates"][0]
    _find_result(run_payload, candidate["nct_id"]).update(
        _result(candidate, "direct_competitor")
    )
    report = qc.build_report(snapshot, run_payload)
    assert "invalid_direct_competitor" in _issue_codes(report)


def test_direct_requires_candidate_dimensions_with_verifiable_source():
    snapshot, run_payload = _valid_pair()
    candidate = snapshot["candidates"][0]
    result = _find_result(run_payload, candidate["nct_id"])
    result.update(_result(candidate, "direct_competitor"))
    for dimension in result["matching_dimensions"]:
        if dimension["dimension"] in qc.PROTECTED_DIMENSIONS:
            dimension["match"] = "match"
            dimension["detail"] = "显式来源匹配"
    report = qc.build_report(
        snapshot,
        run_payload,
        project_technology_type="small_molecule",
        project_administration_routes=["oral"],
        project_target_mechanism="factor_b",
    )
    assert "invalid_direct_competitor" in _issue_codes(report)


def test_direct_can_pass_when_both_sides_three_dimensions_are_explicit():
    snapshot, run_payload = _valid_pair()
    candidate = snapshot["candidates"][0]
    candidate.update(
        {
            "modality": "small_molecule",
            "route": "oral",
            "target_mechanism": "factor_b",
        }
    )
    result = _find_result(run_payload, candidate["nct_id"])
    result.update(_result(candidate, "direct_competitor"))
    for dimension in result["matching_dimensions"]:
        if dimension["dimension"] in qc.PROTECTED_DIMENSIONS:
            dimension["match"] = "match"
            dimension["detail"] = "显式来源匹配"
    _refresh_snapshot_hash(snapshot, run_payload)
    report = qc.build_report(
        snapshot,
        run_payload,
        project_technology_type="small_molecule",
        project_administration_routes=["oral"],
        project_target_mechanism="factor_b",
    )
    assert report["accepted"] is True


def test_document_flags_and_role_are_deterministic():
    snapshot, run_payload = _valid_pair()
    candidate = snapshot["candidates"][0]
    nct_id = candidate["nct_id"]
    candidate["public_documents"] = [
        {
            "document_id": "ctgov_protocol",
            "document_type": "protocol",
            "filename": "Protocol.pdf",
            "download_url": (
                f"https://clinicaltrials.gov/ProvidedDocs/01/{nct_id}/Protocol.pdf"
            ),
        },
        {
            "document_id": "ctgov_sap",
            "document_type": "sap",
            "filename": "SAP.pdf",
            "download_url": (
                f"https://clinicaltrials.gov/ProvidedDocs/01/{nct_id}/SAP.pdf"
            ),
        },
    ]
    result = _find_result(run_payload, nct_id)
    result["document_suitability"] = {
        "has_public_protocol": True,
        "has_public_sap": True,
        "document_role": "可参考口服补体抑制剂",
    }
    _refresh_snapshot_hash(snapshot, run_payload)
    report = qc.build_report(snapshot, run_payload)
    assert "document_suitability_mismatch" in _issue_codes(report)


def test_other_public_document_is_valid_source_but_not_protocol_or_sap():
    snapshot, run_payload = _valid_pair()
    candidate = snapshot["candidates"][0]
    nct_id = candidate["nct_id"]
    candidate["public_documents"] = [
        {
            "document_id": "ctgov_icf",
            "document_type": "other",
            "filename": "ICF.pdf",
            "download_url": (
                f"https://clinicaltrials.gov/ProvidedDocs/01/{nct_id}/ICF.pdf"
            ),
        }
    ]
    _refresh_snapshot_hash(snapshot, run_payload)
    report = qc.build_report(snapshot, run_payload)
    assert report["accepted"] is True


def test_provider_model_and_prompt_are_checked_at_run_and_chunk_levels():
    snapshot, run_payload = _valid_pair()
    run_payload["run"]["provider"] = "other"
    run_payload["run"]["chunks"][0]["provenance"]["prompt_version"] = "old"
    report = qc.build_report(snapshot, run_payload)
    assert "run_provider_mismatch" in _issue_codes(report)
    assert "chunk_prompt_version_mismatch" in _issue_codes(report)


def test_snapshot_hash_is_recomputed_with_service_algorithm():
    snapshot, run_payload = _valid_pair()
    run_payload["run"]["snapshot_hash"] = "0" * 64
    report = qc.build_report(snapshot, run_payload)
    assert "snapshot_hash_mismatch" in _issue_codes(report)


def test_five_chunks_and_67_unique_results_are_required():
    snapshot, run_payload = _valid_pair()
    run_payload["run"]["chunks"].pop()
    report = qc.build_report(snapshot, run_payload)
    codes = _issue_codes(report)
    assert "unexpected_chunk_count" in codes
    assert "unexpected_result_count" in codes
    assert "missing_result_nct_id" in codes


def test_unknown_project_dimension_must_remain_unknown():
    snapshot, run_payload = _valid_pair()
    result = run_payload["run"]["chunks"][0]["results"][0]
    next(
        item
        for item in result["matching_dimensions"]
        if item["dimension"] == "route"
    )["match"] = "match"
    report = qc.build_report(snapshot, run_payload)
    assert "unknown_project_dimension_not_protected" in _issue_codes(report)


def test_reason_must_agree_with_indirect_classification():
    snapshot, run_payload = _valid_pair()
    run_payload["run"]["chunks"][0]["results"][0][
        "reason"
    ] = "适应症不同，不纳入竞品篮子。"
    report = qc.build_report(snapshot, run_payload)
    assert "indirect_reason_inconsistent" in _issue_codes(report)


def test_unsupported_high_risk_claim_is_flagged():
    snapshot, run_payload = _valid_pair()
    run_payload["run"]["chunks"][0]["results"][0][
        "reason"
    ] += "候选为口服补体抑制剂。"
    report = qc.build_report(snapshot, run_payload)
    assert "unsupported_high_risk_claim" in _issue_codes(report)


def test_intervention_code_containing_c5_anchors_repeated_c5_text():
    snapshot, run_payload = _valid_pair()
    candidate = snapshot["candidates"][0]
    candidate["interventions"][0]["name"] = "ALN-CC5"
    result = _find_result(run_payload, candidate["nct_id"])
    result["reason"] += "候选干预名称包含C5。"
    _refresh_snapshot_hash(snapshot, run_payload)
    report = qc.build_report(snapshot, run_payload)
    assert "unsupported_high_risk_claim" not in _issue_codes(report)


def test_all_source_urls_and_locators_are_required():
    snapshot, run_payload = _valid_pair()
    snapshot["candidates"][0]["study_record_url"] = ""
    _refresh_snapshot_hash(snapshot, run_payload)
    report = qc.build_report(snapshot, run_payload)
    assert "invalid_study_record_url" in _issue_codes(report)


def test_public_document_requires_locator_and_source_url():
    snapshot, run_payload = _valid_pair()
    candidate = snapshot["candidates"][0]
    candidate["public_documents"] = [
        {
            "document_id": "",
            "document_type": "protocol",
            "filename": "Protocol.pdf",
            "download_url": "",
        }
    ]
    result = _find_result(run_payload, candidate["nct_id"])
    result["document_suitability"] = {
        "has_public_protocol": True,
        "has_public_sap": False,
        "document_role": "已提供公开方案",
    }
    _refresh_snapshot_hash(snapshot, run_payload)
    report = qc.build_report(snapshot, run_payload)
    codes = _issue_codes(report)
    assert "missing_document_locator" in codes
    assert "invalid_document_source_url" in codes


def test_snapshot_query_url_must_be_ctgov_https():
    snapshot, run_payload = _valid_pair()
    snapshot["query_url"] = "https://example.invalid/api/v2/studies"
    _refresh_snapshot_hash(snapshot, run_payload)
    report = qc.build_report(snapshot, run_payload)
    assert "invalid_snapshot_query_url" in _issue_codes(report)


def test_cli_emits_json_and_returns_zero_for_valid_pair(tmp_path, capsys):
    snapshot, run_payload = _valid_pair()
    snapshot_path = tmp_path / "snapshot.json"
    run_path = tmp_path / "run.json"
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
    run_path.write_text(json.dumps(run_payload), encoding="utf-8")
    exit_code = qc.main([str(snapshot_path), str(run_path)])
    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["accepted"] is True


def test_inputs_are_not_mutated():
    snapshot, run_payload = _valid_pair()
    snapshot_before = copy.deepcopy(snapshot)
    run_before = copy.deepcopy(run_payload)
    qc.build_report(snapshot, run_payload)
    assert snapshot == snapshot_before
    assert run_payload == run_before
