from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from services.api.app.monitoring_ai_contracts import (
    MonitoringAiCandidate,
    MonitoringAiClaim,
    MonitoringAiClaimKind,
    MonitoringAiEvidence,
    MonitoringAiSourceBinding,
    MonitoringAiTaskType,
)


HASH = "a" * 64


@pytest.mark.parametrize(
    "declared_hash",
    [
        123,
        "A" * 64,
        " " + HASH,
        HASH + " ",
        "g" * 64,
        "a" * 63,
    ],
)
def test_source_binding_hash_is_exact_lowercase(declared_hash: object) -> None:
    with pytest.raises(ValidationError):
        MonitoringAiSourceBinding(
            source_entry_id="source-listing",
            source_content_sha256=declared_hash,
        )


@pytest.mark.parametrize("field_name", ["source_content_sha256", "input_revision_sha256"])
@pytest.mark.parametrize(
    "declared_hash",
    ["A" * 64, " " + HASH, HASH + " ", "g" * 64, "a" * 63],
)
def test_evidence_hashes_are_not_normalized(
    field_name: str,
    declared_hash: str,
) -> None:
    payload = {
        "evidence_id": "evidence-001",
        "source_entry_id": "source-listing",
        "source_content_sha256": HASH,
        "locator": "listing:LB:row:1",
        "raw_fields": {"domain": "LB"},
        "input_revision_sha256": HASH,
    }
    payload[field_name] = declared_hash

    with pytest.raises(ValidationError, match="evidence hashes must be lowercase SHA-256"):
        MonitoringAiEvidence(**payload)


@pytest.mark.parametrize(
    "declared_hash",
    ["A" * 64, " " + HASH, HASH + " ", "g" * 64, "a" * 63],
)
def test_candidate_input_revision_hash_is_not_normalized(declared_hash: str) -> None:
    evidence = MonitoringAiEvidence(
        evidence_id="evidence-001",
        source_entry_id="source-listing",
        source_content_sha256=HASH,
        locator="listing:LB:row:1",
        raw_fields={"domain": "LB"},
        input_revision_sha256=HASH,
    )
    claim = MonitoringAiClaim(
        claim_id="claim-001",
        kind=MonitoringAiClaimKind.RECOMMENDATION,
        text="建议继续核对字段上下文。",
        confidence=0.85,
        uncertainty="仍需医学经理确认。",
        user_action="请确认。",
        evidence_ids=(evidence.evidence_id,),
    )

    with pytest.raises(ValidationError, match="candidate input revision must be lowercase SHA-256"):
        MonitoringAiCandidate(
            candidate_id="candidate-001",
            job_id="job-001",
            project_id="project-001",
            task_type=MonitoringAiTaskType.LISTING_FIELD_MAPPING,
            candidate_type="field_mapping",
            title="字段映射候选",
            claims=(claim,),
            evidence=(evidence,),
            input_revision_sha256=declared_hash,
            prompt_version="prompt-v1",
            created_at=datetime(2026, 8, 5, tzinfo=timezone.utc),
        )


def test_valid_lowercase_hashes_are_preserved_exactly() -> None:
    binding = MonitoringAiSourceBinding(
        source_entry_id="source-listing",
        source_content_sha256=HASH,
    )
    assert binding.source_content_sha256 == HASH
