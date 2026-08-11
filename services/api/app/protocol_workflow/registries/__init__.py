"""Role, Skill and Harness registry loader for Protocol v3 (Task 1.7).

This package is the strict, fail-closed boundary that turns the closed,
versioned registry documents under
``config/medical_writing/protocol_v3/`` into typed, immutable Python objects.

Design authority: frozen plan Task 1.7 and
``plans/mw_protocol_multi_agent_rearchitecture_design_20260809.md`` sections
5.3 and 17.

The loader enforces the offline discipline mandated by the plan and the
assignment contract:

* documents are *closed* — unknown fields, unknown roles/harnesses, duplicate
  keys, malformed stable ids / versions / schema refs, path escapes and
  credential-shaped keys/values all fail closed;
* the role registry is *credential-free* and records only the user-approved
  target profile; OCR and translation freeze effort to ``none`` and expose no
  thinking control, while the LLM and OCR/translation-support roles may
  configure thinking/effort;
* each skill entry builds a canonical :class:`SkillDefinition` from the
  representable fields and surfaces the remaining typed registry metadata
  (applicability, idempotency policy, error codes, prompt/tool versions,
  rollback) that the frozen canonical contract intentionally does not carry.

The loader performs no network, model, OCR, translation, repository or
filesystem write access.  It is pure and deterministic.
"""

from __future__ import annotations

from app.protocol_workflow.registries.loader import (
    CREDENTIAL_KEY_RE,
    CREDENTIAL_VALUE_RE,
    PATH_ESCAPE_RE,
    REGISTRY_SCHEMA_VERSIONS,
    RegistryDocumentError,
    RegistryLoadError,
    RoleRegistryDocument,
    SkillRegistryDocument,
    load_role_registry,
    load_skill_registry,
)

__all__ = [
    "CREDENTIAL_KEY_RE",
    "CREDENTIAL_VALUE_RE",
    "PATH_ESCAPE_RE",
    "REGISTRY_SCHEMA_VERSIONS",
    "RegistryDocumentError",
    "RegistryLoadError",
    "RoleRegistryDocument",
    "SkillRegistryDocument",
    "load_role_registry",
    "load_skill_registry",
]
