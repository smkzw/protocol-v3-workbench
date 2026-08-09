from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from services.api.app.monitoring_b6_reviewer_packet_revalidation import (
    B6ReviewerPacketRevalidationError,
    B6ReviewerPacketRevalidationIssueCode,
    B6_GATE_PATH,
    C14_GATE_PATH,
    PACKAGE_PATH,
    PACKET_PATH,
    revalidate_b6_reviewer_packet,
)


PACKET_FILE = Path(PACKET_PATH)
PACKAGE_FILE = Path(PACKAGE_PATH)
B6_FILE = Path(B6_GATE_PATH)
C14_FILE = Path(C14_GATE_PATH)


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _inputs() -> tuple[dict, dict, dict, dict]:
    return _read(PACKET_FILE), _read(PACKAGE_FILE), _read(B6_FILE), _read(C14_FILE)


def _observed_files(package: dict) -> dict[str, tuple[int, str]]:
    paths = {PACKET_PATH, PACKAGE_PATH}
    paths.update(item["path"] for item in package["source_manifest"])
    result: dict[str, tuple[int, str]] = {}
    for path in paths:
        data = Path(path).read_bytes()
        result[path] = (len(data), hashlib.sha256(data).hexdigest())
    return result


def _fresh_packet(packet: dict, package: dict, b6: dict, c14: dict, observed: dict) -> dict:
    fresh = deepcopy(packet)
    fresh["mode"] = "read_only_reviewer_packet"
    fresh["formal_package_sha256"] = package["package_sha256"]
    fresh["formal_package_file_sha256"] = observed[PACKAGE_PATH][1]
    fresh["b6_gate"] = {
        **b6["gate"],
        "migration_write_permitted": b6["migration_write_permitted"],
        "source_file": B6_GATE_PATH,
        "source_sha256": observed[B6_GATE_PATH][1],
    }
    fresh["c14_gate"] = {
        **c14,
        "source_file": C14_GATE_PATH,
        "source_sha256": observed[C14_GATE_PATH][1],
    }
    return fresh


def test_current_packet_is_stale_against_current_gate_and_package() -> None:
    packet, package, b6, c14 = _inputs()
    report = revalidate_b6_reviewer_packet(
        packet,
        package,
        b6,
        c14,
        observed_files=_observed_files(package),
    )

    codes = {issue.code for issue in report.issues}
    assert report.status == "stale"
    assert report.evidence_fresh is False
    assert report.packet_file_checked is True
    assert report.package_file_checked is True
    assert report.source_manifest_replay_complete is True
    assert report.packet_outcome_count == 0
    assert report.current_outcome_count == 5
    assert B6ReviewerPacketRevalidationIssueCode.PACKET_B6_SOURCE_MISMATCH in codes
    assert B6ReviewerPacketRevalidationIssueCode.PACKET_PACKAGE_BINDING_MISSING in codes
    assert B6ReviewerPacketRevalidationIssueCode.B6_STATE_MISMATCH in codes
    assert B6ReviewerPacketRevalidationIssueCode.C14_STATE_MISMATCH in codes
    assert B6ReviewerPacketRevalidationIssueCode.AUTHORITY_FLAG_TRUE not in codes
    assert report.medical_approval_granted is False
    assert report.write_authority is False
    assert report.migration_authority is False
    assert report.activation_allowed is False


def test_hash_bound_packet_can_be_fresh_without_reviewer_outcomes() -> None:
    packet, package, b6, c14 = _inputs()
    observed = _observed_files(package)
    fresh = _fresh_packet(packet, package, b6, c14, observed)
    report = revalidate_b6_reviewer_packet(
        fresh,
        package,
        b6,
        c14,
        observed_files=observed,
    )

    assert report.status == "fresh"
    assert report.evidence_fresh is True
    assert report.source_manifest_replay_complete is True
    assert report.packet_gate_binding_verified is True
    assert report.candidate_binding_verified is True
    assert report.current_outcome_binding_verified is True
    assert report.authority_safe is True
    assert report.issues == ()


def test_refresh_packet_can_use_explicit_new_workspace_paths() -> None:
    packet, package, b6, c14 = _inputs()
    observed = _observed_files(package)
    fresh = _fresh_packet(packet, package, b6, c14, observed)
    refresh_packet_path = (
        "records/active_slices/medical_monitoring_b6_packet_freshness_20260803/"
        "B6_REVIEW_PACKET_REFRESH.json"
    )
    refresh_package_path = (
        "records/active_slices/medical_monitoring_b6_packet_freshness_20260803/"
        "FORMAL_PACKAGE_SNAPSHOT.json"
    )
    observed[refresh_packet_path] = observed.pop(PACKET_PATH)
    observed[refresh_package_path] = observed.pop(PACKAGE_PATH)
    report = revalidate_b6_reviewer_packet(
        fresh,
        package,
        b6,
        c14,
        observed_files=observed,
        packet_path=refresh_packet_path,
        package_path=refresh_package_path,
    )

    assert report.status == "fresh"
    assert report.issues == ()


def test_mutated_source_observation_blocks_freshness() -> None:
    packet, package, b6, c14 = _inputs()
    observed = _observed_files(package)
    observed[B6_GATE_PATH] = (observed[B6_GATE_PATH][0], "0" * 64)
    report = revalidate_b6_reviewer_packet(
        _fresh_packet(packet, package, b6, c14, _observed_files(package)),
        package,
        b6,
        c14,
        observed_files=observed,
    )

    codes = {issue.code for issue in report.issues}
    assert report.status == "stale"
    assert B6ReviewerPacketRevalidationIssueCode.OBSERVED_FILE_SHA256_MISMATCH in codes
    assert B6ReviewerPacketRevalidationIssueCode.PACKET_B6_SOURCE_MISMATCH in codes


def test_candidate_fingerprint_drift_is_not_repaired() -> None:
    packet, package, b6, c14 = _inputs()
    observed = _observed_files(package)
    fresh = _fresh_packet(packet, package, b6, c14, observed)
    fresh["candidates"][0]["candidate_fingerprint"] = "f" * 64
    report = revalidate_b6_reviewer_packet(
        fresh,
        package,
        b6,
        c14,
        observed_files=observed,
    )

    assert report.status == "stale"
    assert B6ReviewerPacketRevalidationIssueCode.CANDIDATE_SET_MISMATCH in {
        issue.code for issue in report.issues
    }


def test_authority_flag_true_is_rejected_even_with_matching_hashes() -> None:
    packet, package, b6, c14 = _inputs()
    observed = _observed_files(package)
    fresh = _fresh_packet(packet, package, b6, c14, observed)
    fresh["authority"]["activation_allowed"] = True
    report = revalidate_b6_reviewer_packet(
        fresh,
        package,
        b6,
        c14,
        observed_files=observed,
    )

    assert report.status == "stale"
    assert report.authority_safe is False
    assert B6ReviewerPacketRevalidationIssueCode.AUTHORITY_FLAG_TRUE in {
        issue.code for issue in report.issues
    }


@pytest.mark.parametrize(
    "authority_field",
    ("review_outcome_present", "medical_approval_present", "engineering_approval_present"),
)
def test_outcome_present_authority_flags_are_rejected(
    authority_field: str,
) -> None:
    packet, package, b6, c14 = _inputs()
    observed = _observed_files(package)
    fresh = _fresh_packet(packet, package, b6, c14, observed)
    fresh["authority"][authority_field] = True

    report = revalidate_b6_reviewer_packet(
        fresh,
        package,
        b6,
        c14,
        observed_files=observed,
    )

    assert report.status == "stale"
    assert report.authority_safe is False
    assert B6ReviewerPacketRevalidationIssueCode.AUTHORITY_FLAG_TRUE in {
        issue.code for issue in report.issues
    }


def test_current_gate_write_or_migration_flag_true_fails_closed() -> None:
    packet, package, b6, c14 = _inputs()
    observed = _observed_files(package)
    fresh = _fresh_packet(packet, package, b6, c14, observed)
    tampered_b6 = deepcopy(b6)
    tampered_b6["migration_write_permitted"] = True
    report = revalidate_b6_reviewer_packet(
        fresh,
        package,
        tampered_b6,
        c14,
        observed_files=observed,
    )

    assert report.status == "stale"
    assert report.authority_safe is False
    assert B6ReviewerPacketRevalidationIssueCode.AUTHORITY_FLAG_TRUE in {
        issue.code for issue in report.issues
    }


def test_duplicate_current_outcome_id_is_not_folded_into_a_fresh_binding() -> None:
    packet, package, b6, c14 = _inputs()
    observed = _observed_files(package)
    fresh = _fresh_packet(packet, package, b6, c14, observed)
    tampered_b6 = deepcopy(b6)
    tampered_b6["outcomes"] = [*tampered_b6["outcomes"], deepcopy(tampered_b6["outcomes"][0])]

    report = revalidate_b6_reviewer_packet(
        fresh,
        package,
        tampered_b6,
        c14,
        observed_files=observed,
    )

    assert report.status == "stale"
    assert B6ReviewerPacketRevalidationIssueCode.CURRENT_OUTCOME_BINDING_MISMATCH in {
        issue.code for issue in report.issues
    }


def test_missing_observation_map_fails_closed_without_file_io_assumption() -> None:
    packet, package, b6, c14 = _inputs()
    report = revalidate_b6_reviewer_packet(packet, package, b6, c14)

    assert report.status == "stale"
    assert report.evidence_fresh is False
    assert B6ReviewerPacketRevalidationIssueCode.OBSERVED_FILES_MISSING in {
        issue.code for issue in report.issues
    }


@pytest.mark.parametrize("value", (None, [], "packet"))
def test_non_mapping_inputs_are_rejected(value: object) -> None:
    packet, package, b6, c14 = _inputs()
    with pytest.raises(B6ReviewerPacketRevalidationError):
        revalidate_b6_reviewer_packet(value, package, b6, c14)  # type: ignore[arg-type]
