"""Product profile selection: which LLM identity the workbench operates.

Per the 2026-09-13 goal the product default is the DeepSeek profile
(``role_registry.deepseek.json`` — model ``deepseek-v4-flash``, reasoning
effort ``max``, credentials bound to the stored omp deepseek key that omp's
opencode-go binding uses).  The historical GLM profile remains reachable
only as the explicitly selected alternative — the same no-silent-fallback
discipline the 1R.6 decision established, inverted by the newer goal.
"""
from __future__ import annotations

import os

from app.protocol_workflow.runtime.omp_credentials import (
    resolve_omp_deepseek_key,
    resolve_omp_zhipu_key,
)
from app.protocol_workflow.runtime.product_profiles import (
    select_role_registry_document,
)

#: Environment variable read at lazy-factory build time only.
PRODUCT_PROFILE_ENV = "WORKBENCH_PROTOCOL_V3_PRODUCT_PROFILE"

#: Profile ids.
PROFILE_DEEPSEEK = "deepseek"
PROFILE_GLM = "glm"


def resolve_product_profile(environ: "os._Environ | dict | None" = None) -> str:
    """Resolve the active product profile from the environment.

    Default per the 2026-09-13 goal: ``deepseek``.  Setting the variable to
    ``glm`` selects the historical profile (useful for A/B confirmation);
    unknown values fail closed here rather than at dispatch time.
    """
    env = os.environ if environ is None else environ
    value = (env.get(PRODUCT_PROFILE_ENV) or PROFILE_DEEPSEEK).strip().lower()
    if value not in (PROFILE_DEEPSEEK, PROFILE_GLM):
        raise ValueError(f"unknown {PRODUCT_PROFILE_ENV} profile: {value!r}")
    return value


def profile_bindings(profile: str) -> dict:
    """Per-profile registry selector and credential resolver.

    The default DeepSeek profile selects ``role_registry.deepseek.json``
    and the stored omp deepseek key; the GLM alternative keeps
    ``role_registry.json`` and the omp zhipu-coding-plan key.
    """
    if profile == PROFILE_DEEPSEEK:
        return {
            "registry_kwargs": {"confirm_alternative": True},
            "credential_resolver": resolve_omp_deepseek_key,
        }
    if profile == PROFILE_GLM:
        return {
            "registry_kwargs": {},
            "credential_resolver": resolve_omp_zhipu_key,
        }
    raise ValueError(f"unknown product profile: {profile!r}")


def select_profile_roles(profile: str):
    """Load the profile's role registry through the strict loader."""
    bindings = profile_bindings(profile)
    return select_role_registry_document(**bindings["registry_kwargs"])
