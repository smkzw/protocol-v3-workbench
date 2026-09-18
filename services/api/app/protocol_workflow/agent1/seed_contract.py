"""Bind research intake to the registered skill and selected product profile."""
import hashlib

from packages.contracts.workbench_contracts.protocol_v3 import (
    NodeExecutionContract, ReasoningEffort, SensitivityTier, SkillDefinition,
)
from app.protocol_workflow.registries.loader import RoleEntry
from app.protocol_workflow.runtime.adapters.zhipu_api import REQUEST_TIMEOUT_SECONDS
from .research_seed import INSTRUCTION


def seed_execution_contract(base: NodeExecutionContract, *, skill: SkillDefinition,
                            role_entry: RoleEntry) -> NodeExecutionContract:
    if skill.skill_definition_id != 'skill.research-seed-proposal' or role_entry.role_kind != 'llm':
        raise ValueError('research_seed_skill_binding_mismatch')
    profile = role_entry.target_profile
    return base.model_copy(update={
        'skill_definition_id': skill.skill_definition_id,
        'role': role_entry.role_id,
        'harness': profile.harness, 'provider': profile.provider, 'model': profile.model,
        'reasoning_effort': ReasoningEffort(role_entry.default_effort),
        'timeout_seconds': REQUEST_TIMEOUT_SECONDS,
        'prompt_sha256': hashlib.sha256(INSTRUCTION.encode('utf-8')).hexdigest(),
        'input_schema_ref': skill.input_schema_ref, 'output_schema_ref': skill.output_schema_ref,
        'allowed_tools': skill.allowed_tools, 'allowed_paths': skill.allowed_paths,
        'allowed_providers': (profile.provider,), 'allowed_regions': profile.regions,
        'sensitivity_tier': SensitivityTier(profile.sensitivity_tier),
    })
