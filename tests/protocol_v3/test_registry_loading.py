"""Focused deterministic registry-loading tests for Protocol v3 Task 1.7.

These tests are *offline and deterministic*: no service, model, OCR,
translation, repository or network is started.  They prove that the closed,
versioned role and skill registry documents load into typed immutable objects
and that every closed-set / schema-version / credential / path-escape /
duplicate / role-thinking violation fails closed.

Design authority: frozen plan Task 1.7 and
``plans/mw_protocol_multi_agent_rearchitecture_design_20260809.md`` sections
5.3 and 17.1.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from app.protocol_workflow.registries import (
    REGISTRY_SCHEMA_VERSIONS,
    RegistryDocumentError,
    load_role_registry,
    load_skill_registry,
)

from packages.contracts.workbench_contracts.protocol_v3 import (
    CanonicalState,
    SideEffectKind,
    SkillDefinition,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
ROLE_REGISTRY_PATH = REPO_ROOT / "config/medical_writing/protocol_v3/role_registry.json"
SKILL_REGISTRY_PATH = (
    REPO_ROOT / "config/medical_writing/protocol_v3/skill_registry.json"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _role_payload() -> dict:
    with ROLE_REGISTRY_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def _skill_payload() -> dict:
    with SKILL_REGISTRY_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


# ---------------------------------------------------------------------------
# Positive: the committed registry documents load and type-check
# ---------------------------------------------------------------------------


def test_role_registry_loads_from_disk() -> None:
    document = load_role_registry(ROLE_REGISTRY_PATH)
    assert document.schema_version == REGISTRY_SCHEMA_VERSIONS["role"]
    assert len(document.roles) == 4


def test_role_registry_declares_exactly_four_product_roles() -> None:
    document = load_role_registry(ROLE_REGISTRY_PATH)
    kinds = {role.role_kind for role in document.roles}
    assert kinds == {"llm", "ocr", "translation", "ocr_translation_support"}
    ids = [role.role_id for role in document.roles]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize(
    "role_kind, expected_thinking, expected_effort",
    [
        ("llm", True, "max"),
        ("ocr", False, "none"),
        ("translation", False, "none"),
        ("ocr_translation_support", True, "max"),
    ],
)
def test_role_thinking_and_effort_discipline(
    role_kind: str, expected_thinking: bool, expected_effort: str
) -> None:
    document = load_role_registry(ROLE_REGISTRY_PATH)
    role = next(role for role in document.roles if role.role_kind == role_kind)
    assert role.thinking_configurable is expected_thinking
    assert role.default_effort == expected_effort
    if role_kind in {"ocr", "translation"}:
        assert role.allowed_efforts == ("none",)
    else:
        assert "none" not in role.allowed_efforts


def test_role_registry_records_exact_credential_free_target_profile() -> None:
    document = load_role_registry(ROLE_REGISTRY_PATH)
    by_kind = {role.role_kind: role for role in document.roles}

    assert by_kind["llm"].target_profile.provider == "deepseek"
    assert by_kind["llm"].target_profile.model == "deepseek-v4-flash"
    assert by_kind["ocr_translation_support"].target_profile.provider == "deepseek"
    assert (
        by_kind["ocr_translation_support"].target_profile.model == "deepseek-v4-flash"
    )

    ocr = by_kind["ocr"].target_profile
    assert ocr.provider == "paddle-official"
    assert ocr.model == "PaddleOCR-VL-1.6"

    translation = by_kind["translation"].target_profile
    assert translation.provider == "local-omlx"
    assert translation.model == "dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX"


def test_skill_registry_loads_from_disk() -> None:
    document = load_skill_registry(SKILL_REGISTRY_PATH)
    assert document.schema_version == REGISTRY_SCHEMA_VERSIONS["skill"]
    assert len(document.skills) >= 1


def test_skill_registry_builds_canonical_skill_definitions() -> None:
    document = load_skill_registry(SKILL_REGISTRY_PATH)
    definitions = document.skill_definitions()
    assert len(definitions) == len(document.skills)
    for definition in definitions:
        assert isinstance(definition, SkillDefinition)
        assert definition.canonical_state is CanonicalState.FROZEN
        assert definition.side_effect_kind in SideEffectKind


def test_skill_entries_carry_registry_metadata_beyond_canonical_contract() -> None:
    document = load_skill_registry(SKILL_REGISTRY_PATH)
    for entry in document.skills:
        # The fields the canonical SkillDefinition does not carry.
        assert entry.applicability.status in {
            "applicable",
            "conditional",
            "not_applicable",
        }
        assert entry.applicability.triggering_fact_paths
        assert entry.idempotency_policy.mode
        assert entry.idempotency_policy.key_basis
        assert entry.error_codes
        assert entry.prompt_version
        assert entry.tool_versions
        assert entry.rollback.method
        assert entry.rollback.preserves


def test_skill_definition_ids_are_unique() -> None:
    document = load_skill_registry(SKILL_REGISTRY_PATH)
    ids = [entry.skill_definition_id for entry in document.skills]
    assert len(ids) == len(set(ids))


# ---------------------------------------------------------------------------
# Negative: fail-closed violations
# ---------------------------------------------------------------------------


def test_unknown_field_fails_closed() -> None:
    payload = _role_payload()
    payload["unexpected_top_level"] = "no"
    with pytest.raises(RegistryDocumentError):
        load_role_registry(payload)


def test_unknown_role_kind_fails_closed() -> None:
    payload = _role_payload()
    payload["roles"][0]["role_kind"] = "sentinel"
    with pytest.raises(RegistryDocumentError):
        load_role_registry(payload)


def test_unknown_schema_version_fails_closed() -> None:
    payload = _role_payload()
    payload["schema_version"] = "protocol-v3-role-registry.v999"
    with pytest.raises(RegistryDocumentError):
        load_role_registry(payload)


def test_duplicate_role_id_fails_closed() -> None:
    payload = _role_payload()
    payload["roles"][0]["role_id"] = payload["roles"][1]["role_id"]
    with pytest.raises(RegistryDocumentError):
        load_role_registry(payload)


def test_missing_fourth_role_kind_fails_closed() -> None:
    payload = _role_payload()
    payload["roles"] = payload["roles"][:3]
    with pytest.raises(RegistryDocumentError):
        load_role_registry(payload)


def test_malformed_role_id_fails_closed() -> None:
    payload = _role_payload()
    payload["roles"][0]["role_id"] = "1 Starts With Digit"
    with pytest.raises(RegistryDocumentError):
        load_role_registry(payload)


def test_ocr_role_with_thinking_enabled_fails_closed() -> None:
    payload = _role_payload()
    ocr = next(role for role in payload["roles"] if role["role_kind"] == "ocr")
    ocr["thinking_configurable"] = True
    with pytest.raises(RegistryDocumentError):
        load_role_registry(payload)


def test_translation_role_with_non_none_effort_fails_closed() -> None:
    payload = _role_payload()
    translation = next(
        role for role in payload["roles"] if role["role_kind"] == "translation"
    )
    translation["default_effort"] = "medium"
    translation["allowed_efforts"] = ["none", "medium"]
    with pytest.raises(RegistryDocumentError):
        load_role_registry(payload)


def test_credential_shaped_key_in_role_registry_fails_closed() -> None:
    payload = _role_payload()
    payload["roles"][0]["target_profile"]["api_key"] = "leak"
    with pytest.raises(RegistryDocumentError):
        load_role_registry(payload)


def test_credential_shaped_value_in_role_registry_fails_closed() -> None:
    payload = _role_payload()
    payload["authority"] = "Bearer abc123.def456.gh789-secret-value"
    with pytest.raises(RegistryDocumentError):
        load_role_registry(payload)


def test_skill_unknown_field_fails_closed() -> None:
    payload = _skill_payload()
    payload["skills"][0]["rogue_field"] = True
    with pytest.raises(RegistryDocumentError):
        load_skill_registry(payload)


def test_skill_duplicate_id_fails_closed() -> None:
    payload = _skill_payload()
    payload["skills"][1]["skill_definition_id"] = payload["skills"][0][
        "skill_definition_id"
    ]
    with pytest.raises(RegistryDocumentError):
        load_skill_registry(payload)


def test_skill_malformed_stable_id_fails_closed() -> None:
    payload = _skill_payload()
    payload["skills"][0]["skill_definition_id"] = "UPPER CASE ID"
    with pytest.raises(RegistryDocumentError):
        load_skill_registry(payload)


def test_skill_unknown_agent_role_fails_closed() -> None:
    payload = _skill_payload()
    payload["skills"][0]["agent_role"] = "drafter"
    with pytest.raises(RegistryDocumentError):
        load_skill_registry(payload)


def test_skill_unknown_side_effect_kind_fails_closed() -> None:
    payload = _skill_payload()
    payload["skills"][0]["side_effect_kind"] = "network_call"
    with pytest.raises(RegistryDocumentError):
        load_skill_registry(payload)


def test_skill_path_escape_fails_closed() -> None:
    payload = _skill_payload()
    payload["skills"][0]["allowed_paths"] = ["../../../etc/passwd"]
    with pytest.raises(RegistryDocumentError):
        load_skill_registry(payload)


def test_skill_absolute_path_fails_closed() -> None:
    payload = _skill_payload()
    payload["skills"][0]["allowed_paths"] = ["/etc/absolute"]
    with pytest.raises(RegistryDocumentError):
        load_skill_registry(payload)


def test_skill_windows_path_fails_closed() -> None:
    payload = _skill_payload()
    payload["skills"][0]["allowed_paths"] = [r"C:\clinical\output"]
    with pytest.raises(RegistryDocumentError, match="escaping or absolute path"):
        load_skill_registry(payload)


def test_skill_credential_in_tool_versions_fails_closed() -> None:
    payload = _skill_payload()
    payload["skills"][0]["tool_versions"]["api_key"] = "sk-leak-12345678901234567890"
    with pytest.raises(RegistryDocumentError):
        load_skill_registry(payload)


def test_skill_duplicate_acceptance_test_id_fails_closed() -> None:
    payload = _skill_payload()
    dup = payload["skills"][0]["acceptance_test_ids"][0]
    payload["skills"][0]["acceptance_test_ids"] = [dup, dup]
    with pytest.raises(RegistryDocumentError):
        load_skill_registry(payload)


def test_role_registry_payload_is_not_mutated_by_loader() -> None:
    payload = _role_payload()
    snapshot = copy.deepcopy(payload)
    load_role_registry(payload)
    assert payload == snapshot


def test_skill_tool_versions_are_deeply_immutable() -> None:
    document = load_skill_registry(SKILL_REGISTRY_PATH)
    tool_versions = document.skills[0].tool_versions
    key = next(iter(tool_versions))
    with pytest.raises(TypeError):
        tool_versions[key] = "mutated"
    with pytest.raises(TypeError):
        tool_versions |= {"another": "mutated"}
    assert document.model_dump()["skills"][0]["tool_versions"]
    assert document.model_dump_json()
