"""Offline profile-selection tests for Protocol v3 Task 1R.6.

Proves the default product profile is the user-approved GLM-5.3-Flash:max
(zhipu-coding-plan) registry and that the DeepSeek registry is reachable only
through an explicit confirmation argument with no silent fallback.  All tests
exercise the real strict registry loader; no service, model or network is
started.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from app.protocol_workflow.runtime.product_profiles import (
    ProfileSelectionError,
    alternative_role_registry_path,
    default_role_registry_path,
    select_role_registry_document,
    select_role_registry_path,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY = REPO_ROOT / "config/medical_writing/protocol_v3/role_registry.json"
ALTERNATIVE_REGISTRY = (
    REPO_ROOT / "config/medical_writing/protocol_v3/role_registry.deepseek.json"
)


# ---------------------------------------------------------------------------
# Path selection: default vs explicitly confirmed alternative
# ---------------------------------------------------------------------------


def test_default_path_is_the_main_role_registry() -> None:
    assert default_role_registry_path() == DEFAULT_REGISTRY
    assert select_role_registry_path(confirm_alternative=False) == DEFAULT_REGISTRY


def test_alternative_path_is_the_deepseek_registry() -> None:
    assert alternative_role_registry_path() == ALTERNATIVE_REGISTRY
    assert select_role_registry_path(confirm_alternative=True) == ALTERNATIVE_REGISTRY


# ---------------------------------------------------------------------------
# Default profile: GLM-5.3-Flash via zhipu-coding-plan (Task 1R.6)
# ---------------------------------------------------------------------------


def test_default_document_loads_via_strict_loader() -> None:
    document = select_role_registry_document(confirm_alternative=False)
    assert len(document.roles) == 4
    kinds = sorted(role.role_kind for role in document.roles)
    assert kinds == ["llm", "ocr", "ocr_translation_support", "translation"]


@pytest.mark.parametrize("role_kind", ["llm", "ocr_translation_support"])
def test_default_llm_roles_target_glm_max(role_kind: str) -> None:
    document = select_role_registry_document(confirm_alternative=False)
    role = next(role for role in document.roles if role.role_kind == role_kind)
    assert role.target_profile.provider == "zhipu-coding-plan"
    assert role.target_profile.model == "glm-5.3-flash"
    assert role.target_profile.harness == "direct-api"
    assert role.thinking_configurable is True
    assert role.default_effort == "max"
    assert role.allowed_efforts == ("low", "high", "max")


def test_default_profile_keeps_ocr_and_translation_unchanged() -> None:
    document = select_role_registry_document(confirm_alternative=False)
    by_kind = {role.role_kind: role for role in document.roles}

    ocr = by_kind["ocr"].target_profile
    assert ocr.provider == "paddle-official"
    assert ocr.model == "PaddleOCR-VL-1.6"
    assert by_kind["ocr"].allowed_efforts == ("none",)

    translation = by_kind["translation"].target_profile
    assert translation.provider == "local-omlx"
    assert translation.model == "dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX"
    assert by_kind["translation"].allowed_efforts == ("none",)


# ---------------------------------------------------------------------------
# Alternative profile: explicit confirmation only, never silent
# ---------------------------------------------------------------------------


def test_alternative_document_loads_and_declares_deepseek_llm_roles() -> None:
    document = select_role_registry_document(confirm_alternative=True)
    assert len(document.roles) == 4
    for role_kind in ("llm", "ocr_translation_support"):
        role = next(role for role in document.roles if role.role_kind == role_kind)
        assert role.target_profile.provider == "deepseek"
        assert role.target_profile.model == "deepseek-v4-flash"
        assert role.target_profile.harness == "direct-api"


def test_alternative_profile_keeps_ocr_and_translation_identical_to_default() -> None:
    default = select_role_registry_document(confirm_alternative=False)
    alternative = select_role_registry_document(confirm_alternative=True)
    by_kind_default = {role.role_kind: role for role in default.roles}
    by_kind_alt = {role.role_kind: role for role in alternative.roles}
    for kind in ("ocr", "translation"):
        assert by_kind_alt[kind].target_profile == by_kind_default[kind].target_profile


def test_missing_alternative_fails_typed_without_fallback(tmp_path: Path) -> None:
    # The typed failure must not silently fall back to the default registry.
    with pytest.raises(ProfileSelectionError, match="no silent fallback"):
        select_role_registry_document(confirm_alternative=True, config_dir=tmp_path)


def test_missing_default_fails_typed(tmp_path: Path) -> None:
    with pytest.raises(ProfileSelectionError, match="default"):
        select_role_registry_document(confirm_alternative=False, config_dir=tmp_path)
