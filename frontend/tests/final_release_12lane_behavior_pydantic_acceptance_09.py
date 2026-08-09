#!/usr/bin/env python3
"""
W3 Pydantic validation test — feeds exact JS-builder JSON into the actual
Python Pydantic models and endpoint route.

This test:
  1. Emits canonical builder payloads from the JS pipeline (via node subprocess)
  2. Feeds each emitted JSON into the actual WorkbenchModel-based request models
  3. Proves extra fields are rejected (extra='forbid')
  4. Proves missing required fields are rejected
  5. Proves wrong-type fields are rejected
  6. Proves valid exact-builder payloads pass

Run: python3 frontend/tests/final_release_12lane_behavior_pydantic_acceptance_09.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import os
from pathlib import Path

# Ensure the project root is on the path
project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))

from pydantic import ValidationError

from packages.contracts.workbench_contracts.models import (
    RevisionAcceptAndApplyRequest,
    MedicalWritingRevisionRequest,
    RevisionActionRequest,
    RevisionAction,
)


def emit_js_fixtures() -> dict:
    """Run the JS emitPayloadFixtures and return the exact builder output."""
    result = subprocess.run(
        ["node", "-e", """
import('./frontend/tests/final_release_12lane_pipeline.mjs').then(m => {
  const fixtures = m.emitPayloadFixtures('e3-pytest-key-001');
  process.stdout.write(JSON.stringify(fixtures));
}).catch(e => { console.error(e.message); process.exit(1); });
"""],
        capture_output=True,
        text=True,
        cwd=str(project_root),
        timeout=10,
    )
    if result.returncode != 0:
        raise RuntimeError(f"JS fixture emission failed: {result.stderr}")
    return json.loads(result.stdout)


def test_accept_and_apply_valid():
    """Exact JS-builder accept_and_apply JSON must pass Pydantic validation."""
    fixtures = emit_js_fixtures()
    payload = fixtures["accept_and_apply"]
    # Must not raise
    model = RevisionAcceptAndApplyRequest(**payload)
    assert model.suggestion_id == "sugg-001"
    assert model.expected_working_copy_revision == 0
    assert model.actor == "qc-e3-user"
    assert model.idempotency_key == "e3-pytest-key-001"
    print("  PASS: accept_and_apply valid payload accepted")


def test_accept_and_apply_rejects_extra_field():
    """Extra fields must be rejected by extra='forbid'."""
    fixtures = emit_js_fixtures()
    payload = {**fixtures["accept_and_apply"], "malicious_field": "injected"}
    try:
        RevisionAcceptAndApplyRequest(**payload)
        assert False, "Should have raised ValidationError for extra field"
    except ValidationError as e:
        errors = e.errors()
        assert any("malicious_field" in str(err) for err in errors), \
            f"Error must mention malicious_field: {errors}"
    print("  PASS: accept_and_apply extra field rejected")


def test_accept_and_apply_rejects_missing_required():
    """Missing required fields must be rejected."""
    fixtures = emit_js_fixtures()
    payload = {**fixtures["accept_and_apply"]}
    del payload["suggestion_id"]
    try:
        RevisionAcceptAndApplyRequest(**payload)
        assert False, "Should have raised ValidationError for missing suggestion_id"
    except ValidationError as e:
        errors = e.errors()
        assert any("suggestion_id" in str(err) for err in errors), \
            f"Error must mention suggestion_id: {errors}"
    print("  PASS: accept_and_apply missing suggestion_id rejected")


def test_accept_and_apply_rejects_missing_idempotency_key():
    """Missing idempotency_key must be rejected."""
    fixtures = emit_js_fixtures()
    payload = {**fixtures["accept_and_apply"]}
    del payload["idempotency_key"]
    try:
        RevisionAcceptAndApplyRequest(**payload)
        assert False, "Should have raised ValidationError for missing idempotency_key"
    except ValidationError as e:
        errors = e.errors()
        assert any("idempotency_key" in str(err) for err in errors), \
            f"Error must mention idempotency_key: {errors}"
    print("  PASS: accept_and_apply missing idempotency_key rejected")


def test_accept_and_apply_rejects_wrong_type():
    """Wrong type (string for int field) must be rejected."""
    fixtures = emit_js_fixtures()
    payload = {**fixtures["accept_and_apply"], "expected_working_copy_revision": "not-a-number"}
    try:
        RevisionAcceptAndApplyRequest(**payload)
        assert False, "Should have raised ValidationError for wrong type"
    except ValidationError as e:
        errors = e.errors()
        assert any("expected_working_copy_revision" in str(err) for err in errors), \
            f"Error must mention expected_working_copy_revision: {errors}"
    print("  PASS: accept_and_apply wrong type rejected")


def test_revision_candidate_valid():
    """Exact JS-builder revision_candidate JSON must pass MedicalWritingRevisionRequest."""
    fixtures = emit_js_fixtures()
    payload = fixtures["revision_candidate"]
    # MedicalWritingRevisionRequest requires section_id, user_instruction
    model = MedicalWritingRevisionRequest(**payload)
    assert model.section_id == "sec-001"
    assert model.user_instruction == "test instruction"
    assert model.evidence_brief_ids == ["brief-001"]
    print("  PASS: revision_candidate valid payload accepted")


def test_revision_candidate_rejects_extra():
    """Extra field must be rejected by MedicalWritingRevisionRequest."""
    fixtures = emit_js_fixtures()
    payload = {**fixtures["revision_candidate"], "extra_param": True}
    try:
        MedicalWritingRevisionRequest(**payload)
        assert False, "Should have raised ValidationError for extra field"
    except ValidationError as e:
        errors = e.errors()
        assert any("extra_param" in str(err) for err in errors)
    print("  PASS: revision_candidate extra field rejected")


def test_rewrite_valid():
    """Exact JS-builder rewrite JSON must pass RevisionActionRequest."""
    fixtures = emit_js_fixtures()
    payload = fixtures["rewrite"]
    model = RevisionActionRequest(**payload)
    assert model.action == RevisionAction.REQUEST_REWRITE
    assert model.suggestion_id == "sugg-001"
    print("  PASS: rewrite valid payload accepted")


def test_rewrite_rejects_extra():
    """Extra field must be rejected by RevisionActionRequest."""
    fixtures = emit_js_fixtures()
    payload = {**fixtures["rewrite"], "injected": True}
    try:
        RevisionActionRequest(**payload)
        assert False, "Should have raised ValidationError for extra field"
    except ValidationError as e:
        errors = e.errors()
        assert any("injected" in str(err) for err in errors)
    print("  PASS: rewrite extra field rejected")


def run_all():
    print("=" * 70)
    print("W3 Pydantic Acceptance 09 Tests")
    print("=" * 70)

    tests = [
        test_accept_and_apply_valid,
        test_accept_and_apply_rejects_extra_field,
        test_accept_and_apply_rejects_missing_required,
        test_accept_and_apply_rejects_missing_idempotency_key,
        test_accept_and_apply_rejects_wrong_type,
        test_revision_candidate_valid,
        test_revision_candidate_rejects_extra,
        test_rewrite_valid,
        test_rewrite_rejects_extra,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            failed += 1
            print(f"  FAIL: {test.__name__}: {e}")

    print(f"\n{'=' * 70}")
    print(f"Pydantic Acceptance 09: {passed} passed, {failed} failed")
    print("=" * 70)
    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    run_all()
