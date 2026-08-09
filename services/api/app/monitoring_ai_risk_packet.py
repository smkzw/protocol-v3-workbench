from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .medical_risk_repository import MedicalRiskRepository
from .monitoring_ai_contracts import (
    MonitoringAiInputRevision,
    MonitoringAiSourceBinding,
    content_sha256,
)
from .monitoring_project_registry import MonitoringProjectRegistry


_SUBJECT_IDENTIFIER_FIELDS = {
    "SUBJID",
    "USUBJID",
    "SUBJECTID",
    "SCREENINGNO",
    "SCRNO",
}
_SITE_IDENTIFIER_FIELDS = {
    "SITEID",
    "SITENO",
    "SITENUM",
    "CENTERID",
    "SITE",
    "SITENM",
    "LBNAM",
}


@dataclass(frozen=True)
class MonitoringAiRiskPacket:
    input_revision: MonitoringAiInputRevision
    risk_instance_id: str
    risk_context: dict[str, Any]
    evidence_packet: tuple[dict[str, Any], ...]


class MonitoringAiRiskPacketResolver:
    """Build a redacted, immutable AI packet from one current risk instance."""

    def __init__(
        self,
        risk_repository: MedicalRiskRepository,
        project_registry: MonitoringProjectRegistry,
    ):
        self.risk_repository = risk_repository
        self.project_registry = project_registry

    def resolve(
        self,
        project_id: str,
        risk_instance_id: str,
    ) -> MonitoringAiRiskPacket:
        requested_risk_id = str(risk_instance_id).strip()
        if not requested_risk_id:
            raise ValueError("risk_instance_id is required")
        adapter = self.project_registry.get(project_id)
        snapshot = self.risk_repository.current_snapshot(project_id)
        self._assert_current_snapshot(adapter, snapshot)
        risk = next(
            (
                item
                for item in self.risk_repository.list_risks(
                    project_id,
                    snapshot.snapshot_id,
                )
                if item.risk_instance_id == requested_risk_id
            ),
            None,
        )
        if risk is None:
            raise KeyError(
                f"current monitoring risk instance is unavailable: "
                f"{requested_risk_id}"
            )
        redacted_title = self._redact_known_identifiers(
            risk.title,
            subject_id=risk.subject_id or "",
            site_id=risk.site_id or "",
        )

        fragments = [
            self._sanitized_fragment(
                adapter.resolve_source_fragment(locator),
                locator=locator,
            )
            for locator in risk.evidence_span_ids
        ]
        self._assert_current_snapshot(adapter, snapshot)
        fragments.sort(key=self._fragment_order)
        derived_source_seed = {
            "project_id": project_id,
            "snapshot_id": snapshot.snapshot_id,
            "source_revision": snapshot.source_revision,
            "rule_profile_revision": snapshot.rule_profile_revision,
            "engine_version": snapshot.engine_version,
            "risk_instance_id": risk.risk_instance_id,
            "risk_key": risk.risk_key,
            "fragments": fragments,
            "rule": {
                "rule_id": risk.rule_id,
                "rationale": risk.rationale,
                "recommended_action": risk.recommended_action,
                "severity": risk.severity.value,
                "status": risk.status.value,
                "batch_delta": risk.batch_delta,
            },
        }
        derived_source_sha256 = content_sha256(derived_source_seed)
        derived_source_id = (
            f"monitoring-risk-evidence:{snapshot.snapshot_id}:"
            f"{risk.risk_instance_id}"
        )
        evidence_packet = [
            self._fragment_evidence(
                project_id=project_id,
                source_entry_id=derived_source_id,
                source_content_sha256=derived_source_sha256,
                fragment=fragment,
            )
            for fragment in fragments
        ]
        evidence_packet.append(
            {
                "evidence_id": "monrisk_"
                + content_sha256(
                    {
                        "source_content_sha256": derived_source_sha256,
                        "kind": "system_rule",
                        "rule_id": risk.rule_id,
                    }
                )[:28],
                "source_entry_id": derived_source_id,
                "source_content_sha256": derived_source_sha256,
                "locator": f"risk:{risk.risk_instance_id}:rule:{risk.rule_id}",
                "quote": risk.rationale.strip(),
                "raw_fields": {
                    "evidence_kind": "system_rule",
                    "risk_title": redacted_title,
                    "primary_category": risk.primary_category,
                    "severity": risk.severity.value,
                    "status": risk.status.value,
                    "batch_delta": risk.batch_delta,
                    "rule_id": risk.rule_id,
                    "recommended_action": risk.recommended_action,
                    "rule_profile_revision": snapshot.rule_profile_revision,
                    "engine_version": snapshot.engine_version,
                },
            }
        )
        revision_token = content_sha256(
            {
                "derived_source_sha256": derived_source_sha256,
                "evidence_ids": [
                    item["evidence_id"] for item in evidence_packet
                ],
            }
        )
        return MonitoringAiRiskPacket(
            input_revision=MonitoringAiInputRevision(
                project_id=project_id,
                risk_snapshot_revision=(
                    f"{snapshot.snapshot_id}:{revision_token[:24]}"
                ),
                rule_pack_revision=snapshot.rule_profile_revision,
                sources=(
                    MonitoringAiSourceBinding(
                        source_entry_id=derived_source_id,
                        source_content_sha256=derived_source_sha256,
                    ),
                ),
            ),
            risk_instance_id=risk.risk_instance_id,
            risk_context={
                "risk_ref": "current-risk",
                "scope": risk.scope_type,
                "primary_category": risk.primary_category,
                "severity": risk.severity.value,
                "status": risk.status.value,
                "batch_delta": risk.batch_delta,
                "title": redacted_title,
                "source_revision": snapshot.source_revision,
            },
            evidence_packet=tuple(evidence_packet),
        )

    @staticmethod
    def _assert_current_snapshot(adapter: Any, snapshot: Any) -> None:
        if (
            adapter.source_revision() != snapshot.source_revision
            or adapter.risk_profile_revision() != snapshot.rule_profile_revision
            or adapter.risk_engine_version() != snapshot.engine_version
        ):
            raise ValueError(
                "current monitoring risk snapshot is stale against project "
                "sources, rules or engine"
            )

    @classmethod
    def _sanitized_fragment(
        cls,
        fragment: Mapping[str, Any],
        *,
        locator: str,
    ) -> dict[str, Any]:
        fields = []
        for item in fragment.get("fields", []):
            field = str(item.get("field", "")).strip()
            value = item.get("value", "")
            upper = field.upper()
            if upper in _SUBJECT_IDENTIFIER_FIELDS:
                value = "<subject-ref>"
            elif upper in _SITE_IDENTIFIER_FIELDS:
                value = "<site-ref>"
            fields.append({"field": field, "value": value})
        source_type = str(fragment.get("source_type", "")).strip()
        text = str(fragment.get("text", "")).strip()
        primary_summary = str(fragment.get("primary_summary", "")).strip()
        return {
            "source_type": source_type,
            "locator_kind": str(fragment.get("locator_kind", "")).strip(),
            "locator": locator,
            "display_locator": str(
                fragment.get("display_locator", locator)
            ).strip(),
            "text": text,
            "primary_summary": primary_summary,
            "fields": fields,
        }

    @staticmethod
    def _redact_known_identifiers(
        value: str,
        *,
        subject_id: str,
        site_id: str,
    ) -> str:
        redacted = str(value)
        if subject_id:
            redacted = redacted.replace(subject_id, "<subject-ref>")
        if site_id:
            redacted = redacted.replace(site_id, "<site-ref>")
        return redacted

    @staticmethod
    def _fragment_order(fragment: Mapping[str, Any]) -> tuple[int, str]:
        source_type = str(fragment.get("source_type", "")).strip()
        priority = {"listing": 0, "protocol": 1}.get(source_type, 2)
        return priority, str(fragment.get("locator", ""))

    @staticmethod
    def _fragment_evidence(
        *,
        project_id: str,
        source_entry_id: str,
        source_content_sha256: str,
        fragment: Mapping[str, Any],
    ) -> dict[str, Any]:
        locator = str(fragment["locator"])
        quote = str(
            fragment.get("primary_summary")
            or fragment.get("text")
            or "原始数据记录已定位。"
        ).strip()
        return {
            "evidence_id": "monrisk_"
            + content_sha256(
                {
                    "project_id": project_id,
                    "source_content_sha256": source_content_sha256,
                    "locator": locator,
                    "fragment": fragment,
                }
            )[:28],
            "source_entry_id": source_entry_id,
            "source_content_sha256": source_content_sha256,
            "locator": locator,
            "quote": quote,
            "raw_fields": {
                "evidence_kind": (
                    "original_data"
                    if fragment.get("source_type") == "listing"
                    else "protocol_basis"
                ),
                "source_type": fragment.get("source_type", ""),
                "display_locator": fragment.get("display_locator", ""),
                "text": fragment.get("text", ""),
                "fields": fragment.get("fields", []),
            },
        }
