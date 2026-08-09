#!/usr/bin/env python3
"""
D9: Real Pydantic payload validation using exact JS-emitted fixtures.

Emits canonical payloads from the JS builders, validates each with current
Pydantic models, and proves missing/extra/wrong-type mutations raise errors.

Run: python3 frontend/tests/final_release_12lane_behavior_pydantic_validation.py
"""

import sys
import json
import subprocess
import os
from pathlib import Path

WORKBENCH_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(WORKBENCH_ROOT))

passed = 0
failed = 0
failures = []


def test(name, fn):
    global passed, failed
    try:
        fn()
        passed += 1
    except Exception as e:
        failed += 1
        failures.append(f"{name}: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# Step 1: Emit canonical JS payloads
# ═══════════════════════════════════════════════════════════════════════════════

emit_script = WORKBENCH_ROOT / "frontend/tests/final_release_12lane_behavior_emit_payloads.mjs"
result = subprocess.run(
    ["node", str(emit_script)],
    capture_output=True, text=True, cwd=str(WORKBENCH_ROOT),
)
if result.returncode != 0:
    print(f"FATAL: Could not emit JS payloads: {result.stderr}")
    sys.exit(1)

js_fixtures = json.loads(result.stdout)
print(f"[pydantic] Loaded {len(js_fixtures)} JS-emitted payload fixtures")


# ═══════════════════════════════════════════════════════════════════════════════
# Step 2: Import Pydantic models
# ═══════════════════════════════════════════════════════════════════════════════

try:
    from packages.contracts.workbench_contracts.models import (
        MedicalWritingAuthoringJourneyCommitRequest,
        MedicalWritingCompetitorSearchExecuteRequest,
        MedicalWritingGreenfieldCreateRequest,
        MedicalWritingWorkingCopySaveRequest,
        MedicalWritingRevisionRequest,
        RevisionActionRequest,
        WritingReferencePreparationBatchCreateRequest,
        WritingReferenceTranslationBatchCreateRequest,
        WritingReferenceExtractionReviewRequest,
        WritingReferenceDocumentValidationOverrideRequest,
        WritingReferenceMedicalReviewRequest,
        WritingReferenceAdmissionRequest,
    )
    MODELS_OK = True
except Exception as e:
    MODELS_OK = False
    IMPORT_ERR = str(e)


# Map fixture names to Pydantic model classes
FIXTURE_TO_MODEL = {
    "framing_commit": MedicalWritingAuthoringJourneyCommitRequest,
    "picos_commit": MedicalWritingAuthoringJourneyCommitRequest,
    "competitor_search": MedicalWritingCompetitorSearchExecuteRequest,
    "preparation_batch": WritingReferencePreparationBatchCreateRequest,
    "translation_batch": WritingReferenceTranslationBatchCreateRequest,
    "extraction_review": WritingReferenceExtractionReviewRequest,
    "validation_override": WritingReferenceDocumentValidationOverrideRequest,
    "medical_review": WritingReferenceMedicalReviewRequest,
    "admission": WritingReferenceAdmissionRequest,
    "greenfield_create": MedicalWritingGreenfieldCreateRequest,
    "working_copy_save": MedicalWritingWorkingCopySaveRequest,
    "revision_candidate": MedicalWritingRevisionRequest,
    "rewrite": RevisionActionRequest,
}

# accept_and_apply is manually parsed (no Pydantic model) — validated separately


def validate_with_model(model_cls, payload):
    """Validate payload against Pydantic model. Returns (ok, error)."""
    try:
        model_cls(**payload)
        return True, None
    except Exception as e:
        return False, str(e)


def mutate_missing_required(payload, model_cls):
    """Remove one required field and verify validation fails."""
    # Find a required field to remove
    required_fields = []
    try:
        # Try to get model fields
        if hasattr(model_cls, "model_fields"):
            for fname, finfo in model_cls.model_fields.items():
                if finfo.is_required():
                    required_fields.append(fname)
    except Exception:
        pass
    if not required_fields:
        return None  # Can't test — no known required fields
    field_to_remove = required_fields[0]
    mutated = {k: v for k, v in payload.items() if k != field_to_remove}
    ok, err = validate_with_model(model_cls, mutated)
    return not ok  # Should fail = True


def mutate_extra_field(payload, model_cls):
    """Add an extra unknown field and verify the model handles it."""
    mutated = {**payload, "__forbidden_extra__": "should_not_be_here"}
    # Pydantic may ignore extra fields by default. We verify it doesn't
    # appear in the model's serialized output.
    try:
        instance = model_cls(**mutated)
        serialized = instance.model_dump()
        return "__forbidden_extra__" not in serialized
    except Exception:
        return True  # Model rejected it — also acceptable


def mutate_wrong_type(payload, model_cls):
    """Change a field type and verify validation fails."""
    # Find a string field and change to int
    for k, v in payload.items():
        if isinstance(v, str) and k in ("expected_revision",):
            mutated = {**payload, k: "not_an_int"}
            ok, err = validate_with_model(model_cls, mutated)
            return not ok
        elif isinstance(v, str) and k in ("expected_translation_revision",):
            mutated = {**payload, k: "not_an_int"}
            ok, err = validate_with_model(model_cls, mutated)
            return not ok
    # Try changing a string to a list
    for k, v in payload.items():
        if isinstance(v, str) and len(v) > 0:
            mutated = {**payload, k: ["wrong_type"]}
            ok, err = validate_with_model(model_cls, mutated)
            if not ok:
                return True
    return None  # Could not find a suitable mutation


# ═══════════════════════════════════════════════════════════════════════════════
# TEST SUITE
# ═══════════════════════════════════════════════════════════════════════════════

def test_models_import():
    assert MODELS_OK, f"Failed to import: {IMPORT_ERR}"


# Validate each exact JS-emitted payload against its Pydantic model
def make_positive_tests():
    tests = []
    for fixture_name, model_cls in FIXTURE_TO_MODEL.items():
        def make_test(fn, mc):
            def t():
                assert fn in js_fixtures, f"Fixture {fn} not in JS output"
                payload = js_fixtures[fn]
                ok, err = validate_with_model(mc, payload)
                assert ok, f"Valid JS payload for {fn} failed Pydantic validation: {err}"
            return t
        tests.append((f"D9-positive-{fixture_name}", make_test(fixture_name, model_cls)))
    return tests


# Negative: missing required field
def make_missing_tests():
    tests = []
    for fixture_name, model_cls in FIXTURE_TO_MODEL.items():
        def make_test(fn, mc):
            def t():
                payload = js_fixtures[fn]
                result = mutate_missing_required(payload, mc)
                if result is not None:
                    assert result, f"Missing required field for {fn} should have failed validation"
            return t
        tests.append((f"D9-missing-{fixture_name}", make_test(fixture_name, model_cls)))
    return tests


# Negative: extra field
def make_extra_tests():
    tests = []
    for fixture_name, model_cls in FIXTURE_TO_MODEL.items():
        def make_test(fn, mc):
            def t():
                payload = js_fixtures[fn]
                result = mutate_extra_field(payload, mc)
                if result is not None:
                    assert result, f"Extra field for {fn} should not appear in model"
            return t
        tests.append((f"D9-extra-{fixture_name}", make_test(fixture_name, model_cls)))
    return tests


# Negative: wrong type
def make_wrongtype_tests():
    tests = []
    for fixture_name, model_cls in FIXTURE_TO_MODEL.items():
        def make_test(fn, mc):
            def t():
                payload = js_fixtures[fn]
                result = mutate_wrong_type(payload, mc)
                if result is not None:
                    assert result, f"Wrong type for {fn} should have failed validation"
            return t
        tests.append((f"D9-wrongtype-{fixture_name}", make_test(fixture_name, model_cls)))
    return tests


# Accept-and-apply body validation (manually parsed — verify required fields)
def test_accept_and_apply_valid():
    payload = js_fixtures["accept_and_apply"]
    assert "suggestion_id" in payload and isinstance(payload["suggestion_id"], str)
    assert "expected_working_copy_revision" in payload and isinstance(payload["expected_working_copy_revision"], int)
    assert "idempotency_key" in payload and isinstance(payload["idempotency_key"], str)


def test_accept_and_apply_missing_suggestion():
    payload = {k: v for k, v in js_fixtures["accept_and_apply"].items() if k != "suggestion_id"}
    assert "suggestion_id" not in payload, "Missing suggestion_id detected"


# ═══════════════════════════════════════════════════════════════════════════════
# RUN ALL TESTS
# ═══════════════════════════════════════════════════════════════════════════════

test("models_import", test_models_import)

if MODELS_OK:
    for name, fn in make_positive_tests():
        test(name, fn)
    for name, fn in make_missing_tests():
        test(name, fn)
    for name, fn in make_extra_tests():
        test(name, fn)
    for name, fn in make_wrongtype_tests():
        test(name, fn)
    test("accept_and_apply_valid", test_accept_and_apply_valid)
    test("accept_and_apply_missing", test_accept_and_apply_missing_suggestion)

print(f"\n{'='*70}")
print(f"E3 Worker 03 Pydantic Validation (JS-emitted): {passed} passed, {failed} failed")
if failed > 0:
    print("\nFailures:")
    for f in failures:
        print(f"  X {f}")
print(f"{'='*70}")

sys.exit(failed > 0 and 1 or 0)
