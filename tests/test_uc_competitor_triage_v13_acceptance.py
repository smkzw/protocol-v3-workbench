from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "scripts" / "qc" / "uc_competitor_triage_v13_acceptance.py"
SPEC = importlib.util.spec_from_file_location("uc_triage_v13_qc", TOOL_PATH)
assert SPEC is not None and SPEC.loader is not None
qc = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(qc)


def _result(nct_id: str, classification: str) -> dict:
    has_protocol = nct_id in (
        qc.PUBLIC_DOCUMENT_RETAIN_SENTINELS
        | qc.PUBLIC_DOCUMENT_EXCLUDE_SENTINELS
    )
    return {
        "nct_id": nct_id,
        "classification": classification,
        "confidence": 0.8,
        "matching_dimensions": [],
        "document_suitability": {
            "has_public_protocol": has_protocol,
            "has_public_sap": has_protocol,
            "document_role": (
                "已提供公开方案与统计分析计划"
                if has_protocol
                else "无公开方案或统计分析计划"
            ),
        },
        "reason": "fixture reason is deliberately not part of acceptance",
        "evidence_gaps": [],
    }


def _valid_run() -> dict:
    required = sorted(
        qc.PHARMACOLOGIC_UC_SENTINELS
        | set(qc.UC_SYNONYM_SENTINELS)
        | set(qc.EXCLUSION_SENTINELS)
        | qc.PUBLIC_DOCUMENT_RETAIN_SENTINELS
        | qc.PUBLIC_DOCUMENT_EXCLUDE_SENTINELS
    )
    used = set(required)
    filler_index = 1
    while len(required) < qc.EXPECTED_CANDIDATE_COUNT:
        nct_id = f"NCT{filler_index:08d}"
        filler_index += 1
        if nct_id in used:
            continue
        used.add(nct_id)
        required.append(nct_id)

    excluded = set(qc.EXCLUSION_SENTINELS)
    results = [
        _result(
            nct_id,
            "excluded" if nct_id in excluded else "indirect_reference",
        )
        for nct_id in required
    ]
    chunks = []
    for chunk_index in range(qc.EXPECTED_CHUNK_COUNT):
        start = chunk_index * 15
        end = min(start + 15, len(results))
        chunk_results = results[start:end]
        chunks.append(
            {
                "chunk_id": f"ct_chunk_{chunk_index:02d}",
                "chunk_index": chunk_index,
                "nct_ids": [result["nct_id"] for result in chunk_results],
                "status": "succeeded",
                "results": chunk_results,
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
    retain = [
        result["nct_id"]
        for result in results
        if result["classification"] in qc.RETAINED_CLASSIFICATIONS
    ]
    exclude = [
        result["nct_id"]
        for result in results
        if result["classification"] == "excluded"
    ]
    return {
        "run_id": "ct_run_uc_v13_fixture",
        "snapshot_id": "wref_search_uc_fixture",
        "status": "review_ready",
        "provider": qc.EXPECTED_PROVIDER,
        "response_model": qc.EXPECTED_MODEL,
        "prompt_version": qc.EXPECTED_PROMPT_VERSION,
        "schema_version": qc.EXPECTED_SCHEMA_VERSION,
        "recommended_retain": retain,
        "recommended_exclude": exclude,
        "chunks": chunks,
    }


def _find_result(run: dict, nct_id: str) -> dict:
    for chunk in run["chunks"]:
        for result in chunk["results"]:
            if result["nct_id"] == nct_id:
                return result
    raise AssertionError(nct_id)


def _sync_recommendations(run: dict) -> None:
    results = [result for chunk in run["chunks"] for result in chunk["results"]]
    run["recommended_retain"] = [
        result["nct_id"]
        for result in results
        if result["classification"] in qc.RETAINED_CLASSIFICATIONS
    ]
    run["recommended_exclude"] = [
        result["nct_id"]
        for result in results
        if result["classification"] == "excluded"
    ]


def _issue_codes(report: dict) -> set[str]:
    return {issue["code"] for issue in report["issues"]}


def test_valid_fixture_passes_contract_but_not_real_run_gate():
    report = qc.build_report(_valid_run(), input_mode="synthetic_fixture")
    assert report["checks_passed"] is True
    assert report["accepted"] is False
    assert report["real_run_confirmed"] is False
    assert report["gate_status"] == "fixture_contract_passed_only"
    assert report["summary"]["result_count"] == 372
    assert report["summary"]["chunk_count"] == 25


def test_same_payload_is_accepted_only_when_explicitly_treated_as_real_run():
    report = qc.build_report(_valid_run(), input_mode="real_run")
    assert report["checks_passed"] is True
    assert report["accepted"] is True
    assert report["real_run_confirmed"] is True


def test_prompt_version_is_required_at_run_and_chunk_levels():
    run = _valid_run()
    run["prompt_version"] = "competitor_triage_deepseek_v10_crswnp_chronicity"
    run["chunks"][0]["provenance"]["prompt_version"] = "old"
    report = qc.build_report(run)
    assert report["accepted"] is False
    assert {
        "run_prompt_version_mismatch",
        "chunk_prompt_version_mismatch",
    } <= _issue_codes(report)


def test_total_uniqueness_and_classification_conservation_are_enforced():
    run = _valid_run()
    duplicate = run["chunks"][0]["results"][0]["nct_id"]
    run["chunks"][0]["results"][1]["nct_id"] = duplicate
    run["chunks"][0]["results"][2]["classification"] = "maybe"
    _sync_recommendations(run)
    report = qc.build_report(run)
    codes = _issue_codes(report)
    assert "duplicate_result_nct_id" in codes
    assert "chunk_result_permutation_mismatch" in codes
    assert "invalid_classification" in codes


def test_clean_pharmacologic_uc_treatment_is_not_systematically_excluded():
    run = _valid_run()
    nct_id = sorted(qc.PHARMACOLOGIC_UC_SENTINELS)[0]
    _find_result(run, nct_id)["classification"] = "excluded"
    _sync_recommendations(run)
    report = qc.build_report(run)
    assert "pharmacologic_uc_study_excluded" in _issue_codes(report)


def test_uc_synonyms_are_retained_without_matching_reason_text():
    run = _valid_run()
    for nct_id in qc.UC_SYNONYM_SENTINELS:
        result = _find_result(run, nct_id)
        result["reason"] = "completely different generated wording"
    report = qc.build_report(run)
    assert report["accepted"] is True

    nct_id = "NCT07335055"
    _find_result(run, nct_id)["classification"] = "excluded"
    _sync_recommendations(run)
    report = qc.build_report(run)
    assert "uc_synonym_excluded" in _issue_codes(report)


def test_non_treatment_and_non_uc_boundaries_must_be_excluded():
    for nct_id in qc.EXCLUSION_SENTINELS:
        run = _valid_run()
        _find_result(run, nct_id)["classification"] = "indirect_reference"
        _sync_recommendations(run)
        report = qc.build_report(run)
        assert "boundary_not_excluded" in _issue_codes(report), nct_id


def test_public_protocol_or_sap_does_not_override_indication_relevance():
    run = _valid_run()
    assert qc.build_report(run)["accepted"] is True

    pouchitis = next(iter(qc.PUBLIC_DOCUMENT_EXCLUDE_SENTINELS))
    _find_result(run, pouchitis)["classification"] = "indirect_reference"
    _sync_recommendations(run)
    report = qc.build_report(run)
    assert "public_document_overrode_indication_boundary" in _issue_codes(report)


def test_known_public_document_flags_are_required():
    run = _valid_run()
    nct_id = sorted(qc.PUBLIC_DOCUMENT_RETAIN_SENTINELS)[0]
    _find_result(run, nct_id)["document_suitability"] = {
        "has_public_protocol": False,
        "has_public_sap": False,
        "document_role": "无公开方案或统计分析计划",
    }
    report = qc.build_report(run)
    assert "expected_public_document_flag_missing" in _issue_codes(report)


def test_recommended_lists_must_equal_per_result_classifications():
    run = _valid_run()
    run["recommended_retain"].pop()
    report = qc.build_report(run)
    assert "recommended_retain_mismatch" in _issue_codes(report)


def test_cli_fixture_exit_code_is_three_and_never_claims_real_acceptance(
    tmp_path, capsys
):
    run_path = tmp_path / "uc_fixture.json"
    run_path.write_text(json.dumps(_valid_run()), encoding="utf-8")
    exit_code = qc.main(["--synthetic-fixture", str(run_path)])
    output = json.loads(capsys.readouterr().out)
    assert exit_code == 3
    assert output["checks_passed"] is True
    assert output["accepted"] is False
    assert output["real_run_confirmed"] is False


def test_cli_real_run_emits_json_and_returns_zero(tmp_path, capsys):
    run_path = tmp_path / "uc_raw_run.json"
    run_path.write_text(json.dumps({"run": _valid_run()}), encoding="utf-8")
    exit_code = qc.main([str(run_path)])
    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["accepted"] is True
    assert output["input_mode"] == "real_run"


def test_cli_missing_input_is_machine_readable(capsys):
    exit_code = qc.main([])
    output = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert output["accepted"] is False
    assert output["gate_status"] == "input_error"


def test_cli_invalid_json_returns_two(tmp_path, capsys):
    run_path = tmp_path / "bad.json"
    run_path.write_text("{", encoding="utf-8")
    exit_code = qc.main([str(run_path)])
    output = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert output["fatal_error"]["type"] == "JSONDecodeError"


def test_inputs_are_not_mutated():
    run = _valid_run()
    before = copy.deepcopy(run)
    qc.build_report(run)
    assert run == before
