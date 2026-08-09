from __future__ import annotations

import pytest

from services.api.app.monitoring_mapping_contract import MonitoringFieldKind
from services.api.app.monitoring_study_adapter_contract import (
    StudyAdapterContractError,
    StudyAdapterDescriptor,
    StudySourceRegistrySnapshot,
    translate_study_config_to_adapter_binding,
)
from services.api.app.monitoring_study_config import (
    CORE_CAPABILITY_IDS,
    StudyCapability,
    StudyCapabilityState,
    StudyFieldMapping,
    StudyMonitoringConfig,
    StudySourceBinding,
    StudySourceKind,
    StudyTreatmentIdentity,
)


def _config() -> StudyMonitoringConfig:
    return StudyMonitoringConfig(
        project_id="project-demo",
        trial_id="trial-demo",
        display_label="Demo study",
        source_bindings=(
            StudySourceBinding(
                binding_id="listing-v1",
                kind=StudySourceKind.LISTING,
                registry_ref="source-registry/study/listing",
                source_revision="listing-rev-1",
                content_sha256="a" * 64,
            ),
            StudySourceBinding(
                binding_id="protocol-v1",
                kind=StudySourceKind.PROTOCOL,
                registry_ref="source-registry/study/protocol",
                source_revision="protocol-rev-1",
                content_sha256="b" * 64,
            ),
        ),
        field_mappings=(
            StudyFieldMapping(
                mapping_id="ae-term",
                domain="EVENTS",
                target_field="AE_TERM",
                source_fields=("AE_TERM",),
                recommended_role="ae.reported_term",
                field_kind=MonitoringFieldKind.SOURCE_COLLECTED,
            ),
        ),
        treatment_identity=StudyTreatmentIdentity(
            investigational_product_role="treatment.identity.investigational_product",
            concomitant_medication_role="cm.non_ip_medication",
            background_treatment_role="treatment.background.standard_of_care",
        ),
        capabilities=tuple(
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
        ),
        protocol_rule_pack_revision="protocol-rules-v1",
    )


def _descriptor(
    config: StudyMonitoringConfig,
    *,
    supported: tuple[str, ...] = CORE_CAPABILITY_IDS,
    source_ids: tuple[str, ...] = ("listing-v1", "protocol-v1"),
) -> StudyAdapterDescriptor:
    return StudyAdapterDescriptor(
        adapter_id="adapter-demo-v1",
        adapter_key="study-adapter/demo",
        project_id=config.project_id,
        trial_id=config.trial_id,
        config_sha256=config.config_sha256,
        source_binding_ids=source_ids,
        supported_capability_ids=supported,
    )


def test_translation_is_read_only_and_hash_bound() -> None:
    config = _config()
    binding = translate_study_config_to_adapter_binding(config, _descriptor(config))
    payload = binding.to_dict()

    assert binding.read_only is True
    assert payload["config_sha256"] == config.config_sha256
    assert payload["registry"]["registry_sha256"] == binding.registry.registry_sha256
    assert payload["binding_sha256"] == binding.binding_sha256
    assert [item["mapping_id"] for item in payload["field_mappings"]] == ["ae-term"]
    assert all(item.state == StudyCapabilityState.FULL for item in binding.capabilities if item.capability_id != "precise_temporal_rules")


def test_translation_makes_adapter_capability_gap_explicit() -> None:
    config = _config()
    descriptor = _descriptor(config, supported=("subject_timeline",))
    binding = translate_study_config_to_adapter_binding(config, descriptor)

    temporal = next(item for item in binding.capabilities if item.capability_id == "precise_temporal_rules")
    profile = next(item for item in binding.capabilities if item.capability_id == "patient_profile")
    assert temporal.state == StudyCapabilityState.LIMITED
    assert temporal.limitation_codes == ("source_date_only",)
    assert profile.state == StudyCapabilityState.UNAVAILABLE
    assert profile.limitation_codes == ("adapter_capability_missing",)


def test_descriptor_identity_and_required_sources_fail_closed() -> None:
    config = _config()
    wrong_project = StudyAdapterDescriptor(
        adapter_id="adapter-demo-v1",
        adapter_key="study-adapter/demo",
        project_id="project-other",
        trial_id=config.trial_id,
        config_sha256=config.config_sha256,
        source_binding_ids=("listing-v1", "protocol-v1"),
        supported_capability_ids=CORE_CAPABILITY_IDS,
    )
    with pytest.raises(StudyAdapterContractError, match="identity"):
        translate_study_config_to_adapter_binding(config, wrong_project)

    with pytest.raises(StudyAdapterContractError, match="omits required"):
        translate_study_config_to_adapter_binding(
            config,
            _descriptor(config, source_ids=("listing-v1",)),
        )


def test_descriptor_unknown_source_and_hash_fail_closed() -> None:
    config = _config()
    with pytest.raises(StudyAdapterContractError, match="unknown source"):
        translate_study_config_to_adapter_binding(
            config,
            _descriptor(config, source_ids=("listing-v1", "protocol-v1", "unknown-v1")),
        )

    with pytest.raises(StudyAdapterContractError, match="does not match"):
        translate_study_config_to_adapter_binding(
            config,
            StudyAdapterDescriptor(
                adapter_id="adapter-demo-v1",
                adapter_key="study-adapter/demo",
                project_id=config.project_id,
                trial_id=config.trial_id,
                config_sha256="f" * 64,
                source_binding_ids=("listing-v1", "protocol-v1"),
                supported_capability_ids=CORE_CAPABILITY_IDS,
            ),
        )


def test_descriptor_cannot_become_writable() -> None:
    config = _config()
    with pytest.raises(StudyAdapterContractError, match="read-only"):
        _descriptor(config).__class__(
            **{**_descriptor(config).__dict__, "read_only": False}
        )


def test_registry_deduplicates_same_source_identity_and_rejects_conflict() -> None:
    listing = StudySourceBinding(
        binding_id="listing-a",
        kind=StudySourceKind.LISTING,
        registry_ref="source-registry/shared/listing",
        source_revision="rev-1",
        content_sha256="a" * 64,
    )
    same_identity = StudySourceBinding(
        binding_id="listing-b",
        kind=StudySourceKind.LISTING,
        registry_ref="source-registry/shared/listing",
        source_revision="rev-1",
        content_sha256="a" * 64,
    )
    snapshot = StudySourceRegistrySnapshot.from_bindings((same_identity, listing))
    assert len(snapshot.bindings) == 1
    assert snapshot.registry_sha256 == StudySourceRegistrySnapshot.from_bindings((listing, same_identity)).registry_sha256

    conflict = StudySourceBinding(
        binding_id="listing-c",
        kind=StudySourceKind.LISTING,
        registry_ref="source-registry/shared/listing",
        source_revision="rev-2",
        content_sha256="c" * 64,
    )
    with pytest.raises(StudyAdapterContractError, match="conflicting"):
        StudySourceRegistrySnapshot.from_bindings((listing, conflict))


def test_registry_order_is_deterministic() -> None:
    config = _config()
    first = StudySourceRegistrySnapshot.from_bindings(config.source_bindings)
    second = StudySourceRegistrySnapshot.from_bindings(tuple(reversed(config.source_bindings)))
    assert first.to_dict() == second.to_dict()

