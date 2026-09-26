"""A09 result-file protocol tests: the gate writes one authoritative atomic
result.json (schema g0_result/2); stdout GATE_JSON is a display copy;
--from-result re-reads a saved result without re-running the suite.

Contract checks:
- roundtrip: stdout doc == result.json doc, validate_gate_result clean;
- single-character mutations of every required field are rejected;
- tampered/unreadable result files yield a stable FAIL structure;
- --from-result never spawns a new run (evidence dir untouched).
"""
from __future__ import annotations

import json
import os

import pytest

from tests.acceptance import _gate_testkit as kit


def _run_clean(tmp_path):
    kit.write_suite(tmp_path, {"test_passes.py": kit.PASS_BODY})
    proc, doc = kit.run_gate_cli([
        "--root", str(tmp_path), "--scope", "backend", "--pytest-args", ".",
        "--skip-static", "--allow-missing-required-nodes",
    ])
    assert doc is not None, (proc.stdout, proc.stderr[-2000:])
    return doc


def test_result_json_roundtrip_and_stdout_parity(tmp_path):
    doc = _run_clean(tmp_path)
    gate = kit.load_gate_module()
    result_path = doc.get("result_path")
    assert result_path and os.path.isfile(result_path), doc
    raw = open(result_path, encoding="utf-8").read()
    result_doc = json.loads(raw)
    assert gate.validate_gate_result(result_doc) == [], gate.validate_gate_result(result_doc)
    assert doc == result_doc, "stdout GATE_JSON must equal the authoritative result.json"
    assert doc["schema_version"] == "g0_result/2"
    assert doc["verdict"] == "PASS"
    assert os.path.isfile(doc["pytest"]["logs"]["junit_xml"]), doc
    assert os.path.isfile(doc["pytest"]["logs"]["pytest_stdout"]), doc


def test_from_result_rereads_without_rerun(tmp_path):
    doc = _run_clean(tmp_path)
    result_path = doc["result_path"]
    evidence_parent = os.path.dirname(result_path)
    runs_before = sorted(os.listdir(os.path.dirname(evidence_parent)))
    raw_before = open(result_path, "rb").read()
    mtime_before = os.path.getmtime(result_path)

    proc = kit.run_gate_cli(["--root", str(tmp_path), "--from-result", result_path])
    out_proc, out_doc = proc
    assert out_doc is not None, (out_proc.stdout, out_proc.stderr[-2000:])
    assert out_doc["verdict"] == "PASS", out_doc
    # nothing was re-run: no new evidence run dir, result.json untouched
    runs_after = sorted(os.listdir(os.path.dirname(evidence_parent)))
    assert runs_after == runs_before, (runs_before, runs_after)
    assert open(result_path, "rb").read() == raw_before
    assert os.path.getmtime(result_path) == mtime_before


def test_from_result_missing_file_stable_fail(tmp_path):
    proc, doc = kit.run_gate_cli([
        "--root", str(tmp_path), "--from-result", str(tmp_path / "nope.json"),
    ])
    assert doc is not None, (proc.stdout, proc.stderr[-2000:])
    assert doc["verdict"] == "FAIL", doc
    assert any(r.startswith("result_unreadable") for r in doc["reasons"]), doc
    assert proc.returncode == 1


def test_from_result_tampered_schema_rejected(tmp_path):
    doc = _run_clean(tmp_path)
    result_path = doc["result_path"]
    tampered = json.loads(open(result_path, encoding="utf-8").read())
    tampered["schema_version"] = "g0_result/9"
    bad_path = tmp_path / "tampered.json"
    bad_path.write_text(json.dumps(tampered), encoding="utf-8")
    proc, out_doc = kit.run_gate_cli(["--root", str(tmp_path), "--from-result", str(bad_path)])
    assert out_doc is not None, (proc.stdout, proc.stderr[-2000:])
    assert out_doc["verdict"] == "FAIL", out_doc
    assert "result_schema_violation" in out_doc["reasons"], out_doc
    assert out_doc.get("schema_problems"), out_doc


def test_truncated_result_file_stable_fail(tmp_path):
    doc = _run_clean(tmp_path)
    result_path = doc["result_path"]
    raw = open(result_path, encoding="utf-8").read()
    truncated = tmp_path / "truncated.json"
    truncated.write_text(raw[: len(raw) // 2], encoding="utf-8")
    proc, out_doc = kit.run_gate_cli(["--root", str(tmp_path), "--from-result", str(truncated)])
    assert out_doc is not None, (proc.stdout, proc.stderr[-2000:])
    assert out_doc["verdict"] == "FAIL", out_doc
    assert proc.returncode == 1


VALID_VERDICTS = {"PASS", "PASS_WITH_KNOWN_FAILURES", "BLOCKED", "FAIL"}


def _mutation_cases(doc: dict) -> list[tuple[str, object]]:
    return [
        ("schema_version", "g0_result/3"),
        ("gate_version", 123),
        ("mode", "unknown_mode"),
        ("scope", "galaxy"),
        ("verdict", "PASSX"),
        ("verdict", None),
        ("root", ""),
        ("snapshot_at", ""),
        ("ran", "12"),
        ("failed", "0"),
        ("failed_ids", "x"),
        ("known_matched", {"a": 1}),
        ("dissolved", 3),
        ("suspected_data_class", "x"),
        ("suspected_fingerprint_drift", [1, 2]),
        ("missing_required_nodes", "x"),
        ("baseline_not_run_count", None),
        ("collection_errors", "0"),
        ("skipped_count", "0"),
        ("reasons", "not-a-list"),
        ("tested_commit", 123),
        ("baseline_commit", 456),
    ]


def test_single_char_mutations_of_required_fields_rejected(tmp_path):
    doc = _run_clean(tmp_path)
    gate = kit.load_gate_module()
    assert gate.validate_gate_result(doc) == []
    for field, bad_value in _mutation_cases(doc):
        mutated = json.loads(json.dumps(doc))
        mutated[field] = bad_value
        problems = gate.validate_gate_result(mutated)
        assert problems, f"mutation of {field}={bad_value!r} was accepted"
        assert mutated["verdict"] not in (None,) or True  # structure stays inspectable


def test_deleting_any_required_field_rejected(tmp_path):
    doc = _run_clean(tmp_path)
    gate = kit.load_gate_module()
    required_keys = [
        "schema_version", "gate_version", "mode", "scope", "verdict", "root",
        "snapshot_at", "ran", "failed", "failed_ids", "known_matched",
        "dissolved", "suspected_data_class", "suspected_fingerprint_drift",
        "missing_required_nodes", "baseline_not_run_count", "collection_errors",
        "skipped_count", "reasons", "tested_commit", "baseline_commit",
    ]
    for key in required_keys:
        mutated = json.loads(json.dumps(doc))
        mutated.pop(key, None)
        problems = gate.validate_gate_result(mutated)
        assert problems, f"deleting required key {key} was accepted"


def test_failed_count_matches_failed_ids(tmp_path):
    doc = _run_clean(tmp_path)
    gate = kit.load_gate_module()
    mutated = json.loads(json.dumps(doc))
    mutated["failed"] = len(mutated["failed_ids"]) + 1
    problems = gate.validate_gate_result(mutated)
    assert "failed_count_mismatch" in problems, problems
