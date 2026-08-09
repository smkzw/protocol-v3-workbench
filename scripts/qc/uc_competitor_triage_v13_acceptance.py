#!/usr/bin/env python3
"""Deterministic acceptance gate for the UC competitor-triage v13 run.

The gate consumes a persisted raw triage run and does not call the product API,
ClinicalTrials.gov, or an LLM. Its clinical boundary sentinels were selected
from the frozen UC search snapshot used by the three-project v13 acceptance
packet.  It validates classification semantics, not exact generated wording.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any


REPORT_VERSION = "uc_competitor_triage_v13_acceptance_v1"
EXPECTED_PROMPT_VERSION = (
    "competitor_triage_deepseek_v13_controlled_condition_qualifiers"
)
EXPECTED_PROVIDER = "deepseek"
EXPECTED_MODEL = "deepseek-v4-pro"
EXPECTED_SCHEMA_VERSION = "competitor_triage_v1"
EXPECTED_CANDIDATE_COUNT = 372
EXPECTED_CHUNK_COUNT = 25

ALLOWED_CLASSIFICATIONS = {
    "direct_competitor",
    "indirect_reference",
    "excluded",
}
RETAINED_CLASSIFICATIONS = {
    "direct_competitor",
    "indirect_reference",
}
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
NCT_RE = re.compile(r"^NCT\d{8}$")

# Clean pharmacologic UC treatment studies spanning spelling variants, mixed
# intervention types, modern titles, and records with/without public documents.
PHARMACOLOGIC_UC_SENTINELS = frozenset(
    {
        "NCT00487539",
        "NCT00656890",
        "NCT01294410",
        "NCT01456052",
        "NCT01658605",
        "NCT02337608",
        "NCT02520284",
        "NCT02768974",
        "NCT03269695",
        "NCT03341962",
        "NCT05061446",
        "NCT07229950",
        "NCT07335055",
        "NCT07535489",
    }
)

# These records prove that common UC orthography and explicit UC population
# wording must not be rejected by a strict condition-string implementation.
UC_SYNONYM_SENTINELS = {
    "NCT00487539": "Colitis, Ulcerative",
    "NCT01658605": "Colitis, Ulcerative with explicit UC treatment title",
    "NCT07229950": "explicit moderately-to-severely active UC population",
    "NCT07335055": "Ulcerative Colitis (UC)",
    "NCT07535489": "descriptive UC population with parenthetical abbreviation",
}

# These records are deliberately outside a pharmacologic UC-treatment basket.
EXCLUSION_SENTINELS = {
    "NCT01296841": "non-pharmacologic telemedicine/device study",
    "NCT02049502": "ulcerative-colitis-associated pouchitis",
    "NCT03167437": "Crohn-only treatment study",
    "NCT06604260": "diagnostic imaging study in mixed IBD population",
    "NCT06604273": "diagnostic study rather than UC treatment",
    "NCT00820365": "generic IBD record without explicit UC evidence",
}

# Attachment availability is orthogonal to indication classification.  The
# first three are UC treatment records with public Protocol/SAP; the pouchitis
# record also has a public Protocol/SAP but must remain excluded.
PUBLIC_DOCUMENT_RETAIN_SENTINELS = frozenset(
    {"NCT03269695", "NCT03341962", "NCT05061446"}
)
PUBLIC_DOCUMENT_EXCLUDE_SENTINELS = frozenset({"NCT02049502"})


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _unwrap_run(run_payload: dict[str, Any]) -> dict[str, Any]:
    run = run_payload.get("run", run_payload)
    if not isinstance(run, dict):
        raise ValueError("run JSON must be a raw run object or contain a 'run' object")
    return run


def _document_flags(result: dict[str, Any]) -> tuple[bool, bool]:
    suitability = result.get("document_suitability")
    if not isinstance(suitability, dict):
        return False, False
    return (
        suitability.get("has_public_protocol") is True,
        suitability.get("has_public_sap") is True,
    )


def build_report(
    run_payload: dict[str, Any],
    *,
    input_mode: str = "real_run",
) -> dict[str, Any]:
    """Build a machine-readable report without mutating the supplied run."""
    if input_mode not in {"real_run", "synthetic_fixture"}:
        raise ValueError("input_mode must be 'real_run' or 'synthetic_fixture'")
    run = _unwrap_run(run_payload)
    issues: list[dict[str, Any]] = []

    def issue(
        check_id: str,
        code: str,
        message: str,
        *,
        nct_id: str = "",
        evidence: Any = None,
    ) -> None:
        item: dict[str, Any] = {
            "check_id": check_id,
            "code": code,
            "severity": "error",
            "message": message,
        }
        if nct_id:
            item["nct_id"] = nct_id
        if evidence is not None:
            item["evidence"] = evidence
        issues.append(item)

    for field, expected in (
        ("prompt_version", EXPECTED_PROMPT_VERSION),
        ("provider", EXPECTED_PROVIDER),
        ("response_model", EXPECTED_MODEL),
        ("schema_version", EXPECTED_SCHEMA_VERSION),
    ):
        if run.get(field) != expected:
            issue(
                "run_identity",
                f"run_{field}_mismatch",
                f"run {field} does not match the UC v13 contract",
                evidence={"expected": expected, "observed": run.get(field)},
            )
    if run.get("status") != "review_ready":
        issue(
            "run_identity",
            "run_not_review_ready",
            "UC acceptance requires a review_ready run",
            evidence={"observed": run.get("status")},
        )

    chunks = run.get("chunks")
    if not isinstance(chunks, list):
        chunks = []
        issue("completeness", "chunks_not_list", "run.chunks must be an array")
    if len(chunks) != EXPECTED_CHUNK_COUNT:
        issue(
            "completeness",
            "unexpected_chunk_count",
            "UC v13 must contain all 25 chunks",
            evidence={"expected": EXPECTED_CHUNK_COUNT, "observed": len(chunks)},
        )

    results: list[dict[str, Any]] = []
    scheduled_ids: list[str] = []
    for chunk_index, chunk in enumerate(chunks):
        if not isinstance(chunk, dict):
            issue("completeness", "invalid_chunk", "each chunk must be an object")
            continue
        chunk_id = str(chunk.get("chunk_id", f"index:{chunk_index}"))
        if chunk.get("status") != "succeeded":
            issue(
                "completeness",
                "chunk_not_succeeded",
                "every UC chunk must succeed",
                evidence={"chunk_id": chunk_id, "status": chunk.get("status")},
            )
        nct_ids = [str(value) for value in chunk.get("nct_ids", [])]
        chunk_results = [
            value for value in chunk.get("results", []) if isinstance(value, dict)
        ]
        result_ids = [str(value.get("nct_id", "")) for value in chunk_results]
        scheduled_ids.extend(nct_ids)
        results.extend(chunk_results)
        if Counter(nct_ids) != Counter(result_ids):
            issue(
                "completeness",
                "chunk_result_permutation_mismatch",
                "chunk results must be a one-to-one permutation of chunk NCT IDs",
                evidence={
                    "chunk_id": chunk_id,
                    "scheduled_count": len(nct_ids),
                    "result_count": len(result_ids),
                },
            )
        provenance = chunk.get("provenance")
        if not isinstance(provenance, dict):
            issue(
                "run_identity",
                "missing_chunk_provenance",
                "each succeeded chunk must retain provenance",
                evidence={"chunk_id": chunk_id},
            )
            continue
        for field, expected in (
            ("prompt_version", EXPECTED_PROMPT_VERSION),
            ("provider", EXPECTED_PROVIDER),
            ("response_model", EXPECTED_MODEL),
            ("schema_version", EXPECTED_SCHEMA_VERSION),
        ):
            if provenance.get(field) != expected:
                issue(
                    "run_identity",
                    f"chunk_{field}_mismatch",
                    f"chunk provenance {field} does not match the UC v13 contract",
                    evidence={
                        "chunk_id": chunk_id,
                        "expected": expected,
                        "observed": provenance.get(field),
                    },
                )
        for hash_field in ("canonical_input_hash", "canonical_output_hash"):
            if not HEX64_RE.fullmatch(str(provenance.get(hash_field, ""))):
                issue(
                    "run_identity",
                    f"invalid_chunk_{hash_field}",
                    f"chunk {hash_field} must be a 64-character hex digest",
                    evidence={"chunk_id": chunk_id},
                )

    result_ids = [str(result.get("nct_id", "")) for result in results]
    if len(results) != EXPECTED_CANDIDATE_COUNT:
        issue(
            "completeness",
            "unexpected_result_count",
            "UC v13 must return one result for each of 372 candidates",
            evidence={"expected": EXPECTED_CANDIDATE_COUNT, "observed": len(results)},
        )
    if len(set(result_ids)) != len(result_ids):
        duplicate_ids = sorted(
            nct_id for nct_id, count in Counter(result_ids).items() if count > 1
        )
        issue(
            "completeness",
            "duplicate_result_nct_id",
            "UC v13 results must be unique by NCT ID",
            evidence={"duplicates": duplicate_ids},
        )
    if Counter(scheduled_ids) != Counter(result_ids):
        issue(
            "completeness",
            "run_result_permutation_mismatch",
            "all scheduled and returned NCT IDs must match exactly",
        )
    invalid_nct_ids = sorted(
        nct_id for nct_id in result_ids if not NCT_RE.fullmatch(nct_id)
    )
    if invalid_nct_ids:
        issue(
            "completeness",
            "invalid_result_nct_id",
            "all result identifiers must be valid NCT IDs",
            evidence={"nct_ids": invalid_nct_ids},
        )

    results_by_id = {
        str(result.get("nct_id", "")): result
        for result in results
        if isinstance(result, dict)
    }
    classification_counts = Counter(
        str(result.get("classification", "")) for result in results
    )
    invalid_classifications = sorted(
        value for value in classification_counts if value not in ALLOWED_CLASSIFICATIONS
    )
    if invalid_classifications:
        issue(
            "classification_conservation",
            "invalid_classification",
            "each result must use an allowed classification",
            evidence={"values": invalid_classifications},
        )
    if sum(classification_counts.values()) != len(results):
        issue(
            "classification_conservation",
            "classification_count_not_conserved",
            "classification counts must sum to the result count",
        )

    observed_retain = {
        nct_id
        for nct_id, result in results_by_id.items()
        if result.get("classification") in RETAINED_CLASSIFICATIONS
    }
    observed_exclude = {
        nct_id
        for nct_id, result in results_by_id.items()
        if result.get("classification") == "excluded"
    }
    for field, expected_ids in (
        ("recommended_retain", observed_retain),
        ("recommended_exclude", observed_exclude),
    ):
        values = run.get(field)
        if not isinstance(values, list) or Counter(map(str, values)) != Counter(
            expected_ids
        ):
            issue(
                "classification_conservation",
                f"{field}_mismatch",
                f"run.{field} must exactly reflect per-result classifications",
                evidence={
                    "expected_count": len(expected_ids),
                    "observed_count": len(values) if isinstance(values, list) else None,
                },
            )

    required_ids = (
        PHARMACOLOGIC_UC_SENTINELS
        | set(UC_SYNONYM_SENTINELS)
        | set(EXCLUSION_SENTINELS)
        | PUBLIC_DOCUMENT_RETAIN_SENTINELS
        | PUBLIC_DOCUMENT_EXCLUDE_SENTINELS
    )
    for nct_id in sorted(required_ids - set(results_by_id)):
        issue(
            "clinical_boundaries",
            "missing_boundary_sentinel",
            "the frozen UC boundary sentinel is missing from the run",
            nct_id=nct_id,
        )

    misexcluded_drug_ids = sorted(PHARMACOLOGIC_UC_SENTINELS & observed_exclude)
    if misexcluded_drug_ids:
        issue(
            "pharmacologic_uc_retention",
            "pharmacologic_uc_study_excluded",
            "clean pharmacologic UC treatment sentinels must not be excluded",
            evidence={"nct_ids": misexcluded_drug_ids},
        )

    for nct_id, expression in UC_SYNONYM_SENTINELS.items():
        result = results_by_id.get(nct_id)
        if result and result.get("classification") not in RETAINED_CLASSIFICATIONS:
            issue(
                "uc_synonym_retention",
                "uc_synonym_excluded",
                "an explicit UC synonym or population expression was excluded",
                nct_id=nct_id,
                evidence={"expression_class": expression},
            )

    for nct_id, boundary in EXCLUSION_SENTINELS.items():
        result = results_by_id.get(nct_id)
        if result and result.get("classification") != "excluded":
            issue(
                "boundary_exclusions",
                "boundary_not_excluded",
                "a non-UC-treatment boundary record was retained",
                nct_id=nct_id,
                evidence={"boundary": boundary},
            )

    for nct_id in sorted(PUBLIC_DOCUMENT_RETAIN_SENTINELS):
        result = results_by_id.get(nct_id)
        if not result:
            continue
        if not any(_document_flags(result)):
            issue(
                "document_independence",
                "expected_public_document_flag_missing",
                "known public Protocol/SAP attachment is not represented",
                nct_id=nct_id,
            )
        if result.get("classification") not in RETAINED_CLASSIFICATIONS:
            issue(
                "document_independence",
                "public_document_uc_treatment_excluded",
                "public attachment availability must not make a UC treatment ineligible",
                nct_id=nct_id,
            )
    for nct_id in sorted(PUBLIC_DOCUMENT_EXCLUDE_SENTINELS):
        result = results_by_id.get(nct_id)
        if not result:
            continue
        if not any(_document_flags(result)):
            issue(
                "document_independence",
                "expected_public_document_flag_missing",
                "known public Protocol/SAP attachment is not represented",
                nct_id=nct_id,
            )
        if result.get("classification") != "excluded":
            issue(
                "document_independence",
                "public_document_overrode_indication_boundary",
                "public attachment availability must not override indication relevance",
                nct_id=nct_id,
            )

    checks_passed = not issues
    real_run_confirmed = input_mode == "real_run"
    accepted = checks_passed and real_run_confirmed
    if input_mode == "synthetic_fixture":
        gate_status = (
            "fixture_contract_passed_only"
            if checks_passed
            else "fixture_contract_failed"
        )
    else:
        gate_status = "passed" if checks_passed else "failed"

    return {
        "report_version": REPORT_VERSION,
        "accepted": accepted,
        "checks_passed": checks_passed,
        "real_run_confirmed": real_run_confirmed,
        "input_mode": input_mode,
        "gate_status": gate_status,
        "run_identity": {
            "run_id": run.get("run_id"),
            "snapshot_id": run.get("snapshot_id"),
            "status": run.get("status"),
            "provider": run.get("provider"),
            "response_model": run.get("response_model"),
            "prompt_version": run.get("prompt_version"),
            "schema_version": run.get("schema_version"),
        },
        "summary": {
            "result_count": len(results),
            "unique_result_count": len(set(result_ids)),
            "chunk_count": len(chunks),
            "classification_counts": dict(sorted(classification_counts.items())),
            "retain_count": len(observed_retain),
            "exclude_count": len(observed_exclude),
            "error_count": len(issues),
        },
        "sentinel_summary": {
            "pharmacologic_uc_checked": len(PHARMACOLOGIC_UC_SENTINELS),
            "pharmacologic_uc_misexcluded": misexcluded_drug_ids,
            "uc_synonym_checked": len(UC_SYNONYM_SENTINELS),
            "boundary_exclusion_checked": len(EXCLUSION_SENTINELS),
            "public_document_retain_checked": len(
                PUBLIC_DOCUMENT_RETAIN_SENTINELS
            ),
            "public_document_exclude_checked": len(
                PUBLIC_DOCUMENT_EXCLUDE_SENTINELS
            ),
        },
        "issues": issues,
        "residual_gate": (
            "Synthetic fixtures validate only the deterministic contract; "
            "a persisted UC v13 raw run is required for real acceptance."
            if input_mode == "synthetic_fixture"
            else "Deterministic acceptance does not replace final medical review "
            "of all 372 natural-language rationales."
        ),
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate a persisted UC competitor-triage v13 raw run."
    )
    parser.add_argument(
        "run_json",
        type=Path,
        nargs="?",
        help="Path to a raw UC v13 run JSON (or an object containing 'run').",
    )
    parser.add_argument(
        "--synthetic-fixture",
        action="store_true",
        help=(
            "Mark the input as a test fixture. Passing checks returns exit 3 "
            "and never reports real-run acceptance."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.run_json is None:
        report = {
            "report_version": REPORT_VERSION,
            "accepted": False,
            "checks_passed": False,
            "real_run_confirmed": False,
            "gate_status": "input_error",
            "fatal_error": {
                "type": "MissingInput",
                "message": "run_json is required",
            },
        }
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 2
    try:
        report = build_report(
            _load_json(args.run_json),
            input_mode=(
                "synthetic_fixture" if args.synthetic_fixture else "real_run"
            ),
        )
    except Exception as exc:
        report = {
            "report_version": REPORT_VERSION,
            "accepted": False,
            "checks_passed": False,
            "real_run_confirmed": False,
            "gate_status": "input_error",
            "fatal_error": {
                "type": type(exc).__name__,
                "message": str(exc),
            },
        }
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 2

    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    if report["accepted"]:
        return 0
    if report["input_mode"] == "synthetic_fixture" and report["checks_passed"]:
        return 3
    return 1


if __name__ == "__main__":
    sys.exit(main())
