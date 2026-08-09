from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from packages.contracts.workbench_contracts.models import (
    RiskCase,
    RiskEvidenceFragmentSnapshot,
)


def capture_risk_evidence(
    adapter: Any,
    risks: Iterable[RiskCase],
    *,
    source_revision: str,
) -> list[RiskCase]:
    captured_at = datetime.now(timezone.utc)
    captured: list[RiskCase] = []
    for risk in risks:
        snapshots: list[RiskEvidenceFragmentSnapshot] = []
        for locator in risk.evidence_span_ids:
            try:
                fragment = adapter.resolve_source_fragment(locator)
                snapshots.append(
                    RiskEvidenceFragmentSnapshot(
                        locator=locator,
                        source_revision=source_revision,
                        captured_at=captured_at,
                        fragment=fragment,
                    )
                )
            except KeyError:
                snapshots.append(
                    _unavailable_snapshot(
                        locator,
                        source_revision,
                        captured_at,
                        "source_fragment_not_found",
                    )
                )
            except ValueError:
                snapshots.append(
                    _unavailable_snapshot(
                        locator,
                        source_revision,
                        captured_at,
                        "source_locator_invalid",
                    )
                )
            except RuntimeError:
                snapshots.append(
                    _unavailable_snapshot(
                        locator,
                        source_revision,
                        captured_at,
                        "source_changed_during_capture",
                    )
                )
        captured.append(risk.model_copy(update={"evidence_snapshots": snapshots}))
    return captured


def public_risk_payload(risk: RiskCase) -> dict[str, Any]:
    payload = risk.model_dump(mode="json")
    payload.pop("evidence_snapshots", None)
    payload["frozen_evidence_count"] = sum(
        1 for item in risk.evidence_snapshots if item.available
    )
    payload["evidence_capture_complete"] = bool(risk.evidence_snapshots) and all(
        item.available for item in risk.evidence_snapshots
    )
    return payload


def frozen_evidence_payload(risk: RiskCase) -> list[dict[str, Any]]:
    return [item.model_dump(mode="json") for item in risk.evidence_snapshots]


def frozen_fragment(
    risk: RiskCase,
    locator: str,
) -> RiskEvidenceFragmentSnapshot | None:
    return next(
        (item for item in risk.evidence_snapshots if item.locator == locator),
        None,
    )


def _unavailable_snapshot(
    locator: str,
    source_revision: str,
    captured_at: datetime,
    error_code: str,
) -> RiskEvidenceFragmentSnapshot:
    return RiskEvidenceFragmentSnapshot(
        locator=locator,
        source_revision=source_revision,
        captured_at=captured_at,
        available=False,
        error_code=error_code,
    )
