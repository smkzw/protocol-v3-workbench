"""Default and explicitly confirmed alternative product profiles (Task 1R.6).

The user-approved 1R.6 decision makes the zhipu-coding-plan GLM-5.3-Flash
registry (``role_registry.json``) the default product profile and keeps the
DeepSeek registry (``role_registry.deepseek.json``) available only as an
explicitly confirmed alternative.  This module is a thin, deterministic
selector over those two documents:

* the default path never returns the alternative document;
* the alternative document is reachable only through the explicit
  ``confirm_alternative=True`` argument — there is no silent fallback in
  either direction;
* documents are loaded exclusively through the strict, fail-closed registry
  loader, so every closed-set/credential/version rule applies unchanged.

The module performs no network, model or credential access.
"""

from __future__ import annotations

from pathlib import Path

from app.protocol_workflow.registries.loader import (
    RoleRegistryDocument,
    load_role_registry,
)

__all__ = [
    "ProfileSelectionError",
    "alternative_role_registry_path",
    "default_role_registry_path",
    "select_role_registry_document",
    "select_role_registry_path",
]

#: Repo root: ``services/api/app/protocol_workflow/runtime/product_profiles.py``
#: is five levels below it.
_REPO_ROOT = Path(__file__).resolve().parents[5]
_DEFAULT_CONFIG_DIR = _REPO_ROOT / "config" / "medical_writing" / "protocol_v3"

_DEFAULT_REGISTRY_NAME = "role_registry.json"
_ALTERNATIVE_REGISTRY_NAME = "role_registry.deepseek.json"


class ProfileSelectionError(RuntimeError):
    """A requested product profile cannot be selected.

    Raised when the requested registry document is missing.  The error is
    actionable and explicitly refuses to fall back to the other profile.
    """


def default_role_registry_path(config_dir: Path | None = None) -> Path:
    """Return the default (GLM) role registry path."""
    base = Path(config_dir) if config_dir is not None else _DEFAULT_CONFIG_DIR
    return base / _DEFAULT_REGISTRY_NAME


def alternative_role_registry_path(config_dir: Path | None = None) -> Path:
    """Return the confirmed-alternative (DeepSeek) role registry path."""
    base = Path(config_dir) if config_dir is not None else _DEFAULT_CONFIG_DIR
    return base / _ALTERNATIVE_REGISTRY_NAME


def select_role_registry_path(
    *,
    confirm_alternative: bool = False,
    config_dir: Path | None = None,
) -> Path:
    """Return the registry path for the requested product profile.

    ``confirm_alternative=False`` (the default) selects the GLM registry.
    ``confirm_alternative=True`` selects the DeepSeek registry and is the only
    way to reach it.
    """
    if confirm_alternative:
        return alternative_role_registry_path(config_dir)
    return default_role_registry_path(config_dir)


def select_role_registry_document(
    *,
    confirm_alternative: bool = False,
    config_dir: Path | None = None,
) -> RoleRegistryDocument:
    """Load the requested product profile through the strict registry loader.

    Raises :class:`ProfileSelectionError` when the requested document does not
    exist; the failure never falls back to the other profile.
    """
    path = select_role_registry_path(
        confirm_alternative=confirm_alternative, config_dir=config_dir
    )
    if not path.is_file():
        profile = "confirmed-alternative DeepSeek" if confirm_alternative else "default"
        raise ProfileSelectionError(
            f"the {profile} product profile registry is missing at {path}; "
            "no silent fallback to the other profile is permitted"
        )
    return load_role_registry(path)
