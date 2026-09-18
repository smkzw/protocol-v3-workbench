"""Task 0.6 permanent functional failure-corpus contracts."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
BUILDER_PATH = ROOT / "scripts/qc/protocol_v3/build_failure_corpus.py"
CORPUS_DIR = ROOT / "tests/fixtures/protocol_v3/failure_corpus"


def _load_builder():
    spec = importlib.util.spec_from_file_location("build_failure_corpus", BUILDER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BUILDER = _load_builder()


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _copy_corpus(tmp_path: Path) -> Path:
    target = tmp_path / "failure_corpus"
    BUILDER.write_corpus(target)
    return target


def _write(path: Path, value: dict) -> None:
    path.write_bytes(BUILDER.json_file_bytes(value))


def test_checked_in_corpus_verifies_and_has_all_required_classes():
    manifest = BUILDER.verify_failure_corpus(CORPUS_DIR)
    assert manifest["fixture_count"] == 8
    assert tuple(manifest["required_files"]) == BUILDER.REQUIRED_FILES
    assert {entry["expected_gate"] for entry in manifest["fixtures"]} == {
        "E0",
        "E3",
        "W1",
        "P1-G1",
    }


def test_rebuild_is_byte_deterministic(tmp_path: Path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    BUILDER.write_corpus(first)
    BUILDER.write_corpus(second)
    for filename in ("manifest.json",) + BUILDER.REQUIRED_FILES:
        assert (first / filename).read_bytes() == (second / filename).read_bytes()


def test_cli_check_passes_on_checked_in_corpus():
    result = subprocess.run(
        [sys.executable, str(BUILDER_PATH), "--check", "--output", str(CORPUS_DIR)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["fixture_count"] == 8


def test_missing_fixture_is_blocking(tmp_path: Path):
    corpus = _copy_corpus(tmp_path)
    (corpus / "heading_only.json").unlink()
    with pytest.raises(BUILDER.FailureCorpusError, match="file set drift"):
        BUILDER.verify_failure_corpus(corpus)


def test_extra_fixture_is_blocking(tmp_path: Path):
    corpus = _copy_corpus(tmp_path)
    _write(corpus / "unexpected.json", {"unexpected": True})
    with pytest.raises(BUILDER.FailureCorpusError, match="file set drift"):
        BUILDER.verify_failure_corpus(corpus)


def test_manifest_expected_gate_change_is_blocking(tmp_path: Path):
    corpus = _copy_corpus(tmp_path)
    manifest = _read(corpus / "manifest.json")
    manifest["fixtures"][0]["expected_gate"] = "W1"
    _write(corpus / "manifest.json", manifest)
    with pytest.raises(BUILDER.FailureCorpusError, match="manifest identity or expected gate drift"):
        BUILDER.verify_failure_corpus(corpus)


@pytest.mark.parametrize("field", ["xfail", "skip"])
def test_negative_fixture_cannot_be_downgraded(tmp_path: Path, field: str):
    corpus = _copy_corpus(tmp_path)
    path = corpus / "r17_thin_eligibility.json"
    fixture = _read(path)
    fixture[field] = True
    _write(path, fixture)
    with pytest.raises(BUILDER.FailureCorpusError, match="sha256 drift"):
        BUILDER.verify_failure_corpus(corpus)


def test_failure_identity_and_code_are_unique_and_pinned():
    manifest = BUILDER.verify_failure_corpus(CORPUS_DIR)
    identities = [entry["failure_identity"] for entry in manifest["fixtures"]]
    codes = [entry["failure_code"] for entry in manifest["fixtures"]]
    assert len(identities) == len(set(identities)) == 8
    assert len(codes) == len(set(codes)) == 8
    assert all(code.startswith("MW-PRO-") for code in codes)


def test_r17_fixtures_disclaim_deleted_runtime_recovery():
    thin = _read(CORPUS_DIR / "r17_thin_eligibility.json")
    heading = _read(CORPUS_DIR / "heading_only.json")
    assert thin["provenance"] == heading["provenance"] == "evidence_reconstructed"
    assert thin["original_runtime_available"] is False
    assert heading["original_runtime_available"] is False
    assert len(thin["payload"]["reconstructed_text"]) == 44
    assert "不是" in thin["payload"]["runtime_note"]
    assert "不声称" in heading["payload"]["runtime_note"]


def test_short_positive_control_proves_length_is_not_the_gate():
    manifest = BUILDER.verify_failure_corpus(CORPUS_DIR)
    control = manifest["positive_controls"][0]
    BUILDER.validate_positive_control(control)
    assert len(control["text"]) < 44
    assert control["claim_type"] == "primary_endpoint_definition"
    assert control["source_locator"]
    assert control["context_before"] and control["context_after"]
    assert control["study_definition_binding"]


def test_d017_skeleton_identity_is_exact_and_compact():
    fixture = _read(CORPUS_DIR / "empty_protocol_d017.json")
    payload = fixture["payload"]
    assert payload["artifact_sha256"] == (
        "bae34f096ef5769a8d025ac03f72d9dfed06278d03faef97dff33beaae9705e9"
    )
    assert (
        payload["heading_count"],
        payload["paragraph_text_character_count"],
        payload["table_count"],
        payload["figure_count"],
        payload["rendered_page_count"],
    ) == (106, 2627, 2, 0, 28)
    assert len(payload["controlled_heading_sample"]) == 4
    assert "content_blocks" not in payload


def test_zero_registry_result_requires_root_cause_investigation():
    payload = _read(CORPUS_DIR / "zero_registry_result.json")["payload"]
    assert payload["result_count"] == 0
    assert payload["root_cause"] == "not_investigated"
    assert payload["connectivity_verified"] is False
    assert payload["synonym_queries_attempted"] == []
    assert payload["incorrect_downstream_state"] == "source_acquisition_complete"


def test_batch_action_cannot_resurrect_a_version_bound_reject():
    payload = _read(CORPUS_DIR / "batch_reject_resurrection.json")["payload"]
    assert payload["latest_item_verdict"] == "reject"
    assert payload["resulting_state"] == "admitted"
    assert payload["new_item_revision"] is None
    assert payload["new_evidence_hash"] is None
    assert payload["rereview_verdict"] is None


def test_unknown_outcome_captures_duplicate_semantic_effect():
    payload = _read(CORPUS_DIR / "unknown_outcome.json")["payload"]
    assert payload["state"] == "unknown_outcome"
    assert payload["transport_attempts"] == 2
    assert payload["same_session_recovery_attempted"] is False
    assert payload["explicit_retry_decision_id"] is None
    assert payload["semantic_effect_count"] == 2


def test_checkpoint_event_split_brain_covers_both_directions():
    payload = _read(CORPUS_DIR / "checkpoint_event_split_brain.json")["payload"]
    assert {
        (case["domain_event_committed"], case["checkpoint_committed"])
        for case in payload["cases"]
    } == {(True, False), (False, True)}
    assert payload["reconciliation_decision_id"] is None


def test_every_fixture_has_durable_source_owner_and_non_vacuous_reason():
    for filename in BUILDER.REQUIRED_FILES:
        fixture = _read(CORPUS_DIR / filename)
        assert fixture["source_locator"]["path"].startswith(
            ("legacy_workbench:", "approved_design:")
        )
        assert fixture["source_locator"]["lines"]
        assert fixture["source_locator"]["evidence"]
        assert fixture["owner"]
        assert fixture["failure_reason"]
        assert fixture["expected_result"] == "fail_closed"


def test_manifest_fixture_hash_tamper_is_detected(tmp_path: Path):
    corpus = _copy_corpus(tmp_path)
    path = corpus / "generic_long_body.json"
    fixture = _read(path)
    fixture["failure_reason"] = "tampered"
    _write(path, fixture)
    with pytest.raises(BUILDER.FailureCorpusError, match="sha256 drift"):
        BUILDER.verify_failure_corpus(corpus)


def test_builder_constants_and_checked_in_manifest_agree():
    expected = BUILDER.build_manifest(BUILDER.build_fixture_documents())
    actual = _read(CORPUS_DIR / "manifest.json")
    assert actual == expected
    assert actual["immutability_contract"] == {
        "allow_fixture_deletion": False,
        "allow_expected_gate_change": False,
        "allow_xfail": False,
        "allow_skip": False,
        "allow_identity_reuse": False,
        "change_requires_new_schema_version": True,
    }
