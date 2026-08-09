from __future__ import annotations

from copy import deepcopy

import pytest

from services.api.app.monitoring_mapping_contract import MonitoringFieldKind
from services.api.app.monitoring_study_config import (
    CORE_CAPABILITY_IDS,
    StudyCapability,
    StudyCapabilityState,
    StudyFieldMapping,
    StudyMonitoringConfig,
    StudyMonitoringConfigError,
    StudySourceBinding,
    StudySourceKind,
    StudyTreatmentIdentity,
)


HASH = "a" * 64


def _sources() -> tuple[StudySourceBinding, ...]:
    return (
        StudySourceBinding(
            binding_id="listing-v1",
            kind=StudySourceKind.LISTING,
            registry_ref="source-registry/study/listing",
            source_revision="listing-rev-1",
            content_sha256=HASH,
        ),
        StudySourceBinding(
            binding_id="protocol-v1",
            kind=StudySourceKind.PROTOCOL,
            registry_ref="source-registry/study/protocol",
            source_revision="protocol-rev-1",
            content_sha256="b" * 64,
        ),
    )


def _capabilities() -> tuple[StudyCapability, ...]:
    return tuple(
        StudyCapability(
            capability_id=capability_id,
            state=(
                StudyCapabilityState.LIMITED
                if capability_id == "precise_temporal_rules"
                else StudyCapabilityState.FULL
            ),
            limitation_codes=(
                ("source_date_only",)
                if capability_id == "precise_temporal_rules"
                else ()
            ),
            evidence_ids=(f"evidence-{capability_id}",),
        )
        for capability_id in CORE_CAPABILITY_IDS
    )


def _config() -> StudyMonitoringConfig:
    return StudyMonitoringConfig(
        project_id="project-demo",
        trial_id="trial-demo",
        display_label="Demo study",
        source_bindings=_sources(),
        field_mappings=(
            StudyFieldMapping(
                mapping_id="ae-term",
                domain="EVENTS",
                target_field="AE_TERM",
                source_fields=("AE_TERM",),
                recommended_role="ae.reported_term",
                field_kind=MonitoringFieldKind.SOURCE_COLLECTED,
            ),
            StudyFieldMapping(
                mapping_id="pt-code",
                domain="EVENTS",
                target_field="PT_CODE",
                source_fields=("AE_TERM",),
                recommended_role="coding.meddra.pt_code",
                field_kind=MonitoringFieldKind.STANDARDIZED_CODED,
                standards_reference={"standard": "SDTM", "reference_only": True},
                derivation_lineage={
                    "source_fields": ["AE_TERM"],
                    "coding_system": "MedDRA",
                    "dictionary_version": "27.0",
                },
            ),
        ),
        treatment_identity=StudyTreatmentIdentity(
            investigational_product_role="treatment.identity.investigational_product",
            concomitant_medication_role="cm.non_ip_medication",
            background_treatment_role="treatment.background.standard_of_care",
        ),
        capabilities=_capabilities(),
        protocol_rule_pack_revision="protocol-rules-v1",
        display_labels={"subject": "Subject", "site": "Site"},
    )


def test_config_is_project_neutral_and_hash_bound() -> None:
    config = _config()
    payload = config.to_dict()

    assert payload["source_bindings"][0]["registry_ref"].startswith(
        "source-registry/"
    )
    assert payload["config_sha256"] == config.config_sha256
    assert StudyMonitoringConfig.from_dict(payload).to_dict() == payload
    assert config.capability("precise_temporal_rules").state == (
        StudyCapabilityState.LIMITED
    )


def test_config_hash_is_deterministic_for_display_label_order() -> None:
    first = _config()
    second = StudyMonitoringConfig(
        **{
            **first.__dict__,
            "display_labels": {"site": "Site", "subject": "Subject"},
        }
    )

    assert first.config_sha256 == second.config_sha256


@pytest.mark.parametrize("registry_ref", ["/tmp/listing.xlsx", "~/listing.xlsx", "../listing.xlsx"])
def test_source_binding_rejects_local_paths(registry_ref: str) -> None:
    with pytest.raises(StudyMonitoringConfigError, match="opaque source-registry"):
        StudySourceBinding(
            binding_id="listing-v1",
            kind=StudySourceKind.LISTING,
            registry_ref=registry_ref,
            source_revision="rev-1",
            content_sha256=HASH,
        )


@pytest.mark.parametrize("malformed", [f" {HASH}", HASH.upper(), 123])
def test_source_binding_hash_shape_is_not_coerced(malformed: object) -> None:
    with pytest.raises(
        StudyMonitoringConfigError,
        match="content_sha256 must be a lowercase SHA-256",
    ):
        StudySourceBinding(
            binding_id="listing-v1",
            kind=StudySourceKind.LISTING,
            registry_ref="source-registry/study/listing",
            source_revision="rev-1",
            content_sha256=malformed,
        )


def test_required_listing_and_protocol_sources_are_fail_closed() -> None:
    config = _config()
    with pytest.raises(StudyMonitoringConfigError, match="required protocol"):
        StudyMonitoringConfig(
            **{
                **config.__dict__,
                "source_bindings": (config.source_bindings[0],),
            }
        )


def test_treatment_identity_roles_cannot_alias() -> None:
    with pytest.raises(StudyMonitoringConfigError, match="remain distinct"):
        StudyTreatmentIdentity(
            investigational_product_role="same",
            concomitant_medication_role="same",
            background_treatment_role="background",
        )


def test_mapping_reuses_semantic_contract_and_rejects_sdtm_role() -> None:
    with pytest.raises(ValueError, match="SDTM"):
        StudyFieldMapping(
            mapping_id="bad-role",
            domain="EVENTS",
            target_field="AE_TERM",
            source_fields=("AE_TERM",),
            recommended_role="SDTM.AE.AETERM",
            field_kind=MonitoringFieldKind.SOURCE_COLLECTED,
        )


def test_mapping_rejects_self_referential_derived_lineage() -> None:
    with pytest.raises(ValueError, match="own source"):
        StudyFieldMapping(
            mapping_id="bad-derived",
            domain="SCALES",
            target_field="CHANGE",
            source_fields=("CHANGE", "BASE"),
            recommended_role="scale.change",
            field_kind=MonitoringFieldKind.DETERMINISTIC_DERIVED,
            derivation_lineage={
                "source_fields": ["CHANGE", "BASE"],
                "formula": "CHANGE - BASE",
                "user_confirmed": True,
            },
        )


def test_limited_or_unavailable_capability_requires_limitation() -> None:
    with pytest.raises(StudyMonitoringConfigError, match="requires limitation_codes"):
        StudyCapability(
            capability_id="ae_risk_assessment",
            state=StudyCapabilityState.UNAVAILABLE,
        )


def test_missing_core_capability_is_not_silently_available() -> None:
    config = _config()
    capabilities = tuple(
        item
        for item in config.capabilities
        if item.capability_id != "ecg_risk_assessment"
    )
    with pytest.raises(StudyMonitoringConfigError, match="all core capabilities"):
        StudyMonitoringConfig(**{**config.__dict__, "capabilities": capabilities})


def test_tampered_hash_and_malformed_lists_fail_closed() -> None:
    payload = _config().to_dict()
    tampered = deepcopy(payload)
    tampered["config_sha256"] = "f" * 64
    with pytest.raises(StudyMonitoringConfigError, match="does not match"):
        StudyMonitoringConfig.from_dict(tampered)

    malformed = deepcopy(payload)
    malformed["field_mappings"] = "not-a-list"
    with pytest.raises(StudyMonitoringConfigError, match="field_mappings must be a list"):
        StudyMonitoringConfig.from_dict(malformed)


@pytest.mark.parametrize(
    "malformed",
    [
        f" {_config().config_sha256}",
        _config().config_sha256.upper(),
        123,
    ],
)
def test_declared_config_hash_shape_is_not_coerced(malformed: object) -> None:
    payload = _config().to_dict()
    payload["config_sha256"] = malformed
    with pytest.raises(
        StudyMonitoringConfigError,
        match="config_sha256 must be a lowercase SHA-256",
    ):
        StudyMonitoringConfig.from_dict(payload)
