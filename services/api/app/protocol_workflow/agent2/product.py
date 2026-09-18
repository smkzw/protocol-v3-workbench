"""Lazy product binding; historical first-use probe is not repeated."""
from functools import partial
from pathlib import Path
from app.protocol_workflow.artifacts.local_store import LocalArtifactStore
from app.protocol_workflow.registries import load_skill_registry
from app.protocol_workflow.runtime.product_profiles import select_role_registry_document, default_role_registry_path
from app.protocol_workflow.runtime.product_profile_bindings import (
    profile_bindings,
    resolve_product_profile,
    select_profile_roles,
)
from app.protocol_workflow.runtime.harness import HarnessDispatcher
from app.protocol_workflow.runtime.restored_probe import RestoredZhipuProbePolicy
from app.protocol_workflow.runtime.omp_credentials import resolve_omp_zhipu_key
from app.protocol_workflow.runtime.product_profile_bindings import resolve_product_profile
from app.protocol_workflow.runtime.adapters.zhipu_api import build_zhipu_api_adapter
from app.protocol_workflow.runtime.adapters.deepseek_api import build_deepseek_api_adapter
from app.protocol_workflow.storage.sqlite import build_unit_of_work_factory, build_committed_reservation_repository_factory
from .subgraph import build_regimen_runtime
from .design_workflow import build_design_elements_runtime
from .coordinator import RegimenCoordinator
from .design_coordinator import DesignElementsCoordinator


def create_product_regimen_factory(*, storage_config: dict, prior_probe_receipt: Path,
                                max_input_bytes: int, credential_resolver=resolve_omp_zhipu_key,
                                http_opener=None, product_profile: str = 'glm'):
    """Read approved configuration only; credential material is resolved on call.

    The caller supplies the isolated/product database configuration, approved
    historical probe and explicit complete-input budget. No alternative model,
    first-use re-probe, credential copy or listening server is introduced here.
    """
    if isinstance(max_input_bytes, bool) or not isinstance(max_input_bytes, int) or max_input_bytes <= 0:
        raise ValueError('regimen_product_input_budget_required')
    config = dict(storage_config)
    if product_profile == 'deepseek':
        # DeepSeek product profile (goal 2026-09-13): deepseek registry roles,
        # deepseek direct transport, omp deepseek credential, first-use real
        # probe (the goal-required minimal connectivity check).
        roles = select_profile_roles('deepseek')
        role = next(r for r in roles.roles if r.role_id == 'product-llm' and r.role_kind == 'llm')
        skills = load_skill_registry(default_role_registry_path().with_name('skill_registry.json'))
        skill = next(s for s in skills.skill_definitions() if s.skill_definition_id == 'skill.regimen-design-proposal')
        dispatcher = HarnessDispatcher()
        adapter = partial(build_deepseek_api_adapter, http_opener=http_opener,
                          max_input_bytes=max_input_bytes)
    else:
        roles = select_role_registry_document()
        role = next(r for r in roles.roles if r.role_id == 'product-llm' and r.role_kind == 'llm')
        skills = load_skill_registry(default_role_registry_path().with_name('skill_registry.json'))
        skill = next(s for s in skills.skill_definitions() if s.skill_definition_id == 'skill.regimen-design-proposal')
        dispatcher = HarnessDispatcher(probe_policy=RestoredZhipuProbePolicy(prior_probe_receipt))
        adapter = partial(build_zhipu_api_adapter, credential_resolver=credential_resolver,
                          http_opener=http_opener, max_input_bytes=max_input_bytes)

    def factory(project_id: str) -> RegimenCoordinator:
        store = LocalArtifactStore(str(config['path']) + '.artifacts')
        runtime = build_regimen_runtime(
            project_id=project_id, uow_factory=build_unit_of_work_factory(config),
            reservation_repository_factory=build_committed_reservation_repository_factory(config),
            artifact_store=store, role_entry=role, skill=skill, dispatcher=dispatcher,
            adapter_factory=adapter,
        )
        return RegimenCoordinator(project_id=project_id, branch_id='main', runtime=runtime, artifact_store=store)

    return factory


def create_product_design_elements_factory(*, storage_config: dict, prior_probe_receipt: Path,
                                           max_input_bytes: int,
                                           credential_resolver=resolve_omp_zhipu_key,
                                           http_opener=None, product_profile: str = 'glm'):
    """Same product binding discipline as the regimen factory, for design elements."""
    if isinstance(max_input_bytes, bool) or not isinstance(max_input_bytes, int) or max_input_bytes <= 0:
        raise ValueError('design_elements_product_input_budget_required')
    config = dict(storage_config)
    if product_profile == 'deepseek':
        roles = select_profile_roles('deepseek')
        role = next(r for r in roles.roles if r.role_id == 'product-llm' and r.role_kind == 'llm')
        skills = load_skill_registry(default_role_registry_path().with_name('skill_registry.json'))
        skill = next(s for s in skills.skill_definitions() if s.skill_definition_id == 'skill.design-elements-proposal')
        dispatcher = HarnessDispatcher()
        adapter = partial(build_deepseek_api_adapter, http_opener=http_opener,
                          max_input_bytes=max_input_bytes)
    else:
        roles = select_role_registry_document()
        role = next(r for r in roles.roles if r.role_id == 'product-llm' and r.role_kind == 'llm')
        skills = load_skill_registry(default_role_registry_path().with_name('skill_registry.json'))
        skill = next(s for s in skills.skill_definitions() if s.skill_definition_id == 'skill.design-elements-proposal')
        dispatcher = HarnessDispatcher(probe_policy=RestoredZhipuProbePolicy(prior_probe_receipt))
        adapter = partial(build_zhipu_api_adapter, credential_resolver=credential_resolver,
                          http_opener=http_opener, max_input_bytes=max_input_bytes)

    def factory(project_id: str) -> DesignElementsCoordinator:
        store = LocalArtifactStore(str(config['path']) + '.artifacts')
        runtime = build_design_elements_runtime(
            project_id=project_id, uow_factory=build_unit_of_work_factory(config),
            reservation_repository_factory=build_committed_reservation_repository_factory(config),
            artifact_store=store, role_entry=role, skill=skill, dispatcher=dispatcher,
            adapter_factory=adapter,
        )
        return DesignElementsCoordinator(project_id=project_id, branch_id='main',
            runtime=runtime, artifact_store=store)

    return factory


def lazy_product_regimen_factory(storage_config: dict):
    """Defer profile/probe I/O until the first admitted intake request."""
    import os
    from threading import Lock
    lock = Lock()
    factory = None
    def resolve(project_id: str):
        nonlocal factory
        if factory is None:
            with lock:
                if factory is None:
                    root = Path(__file__).resolve().parents[5]
                    prior = os.environ.get('WORKBENCH_PROTOCOL_V3_PRIOR_PROBE_RECEIPT')
                    receipt = Path(prior).expanduser() if prior else root / 'runs/mw_protocol_v3_1r6_glm_transport_20260905/product_probe_attempt.json'
                    # An application byte limit, not proof of the provider's context ceiling.
                    budget = int(os.environ.get('WORKBENCH_PROTOCOL_V3_MAX_INPUT_BYTES', '2000000'))
                    factory = create_product_regimen_factory(storage_config=storage_config,
                        prior_probe_receipt=receipt, max_input_bytes=budget,
                        product_profile=resolve_product_profile())
        return factory(project_id)
    return resolve


def lazy_product_design_elements_factory(storage_config: dict):
    """Defer profile/probe I/O until the first admitted design-elements request."""
    import os
    from threading import Lock
    lock = Lock()
    factory = None
    def resolve(project_id: str):
        nonlocal factory
        if factory is None:
            with lock:
                if factory is None:
                    root = Path(__file__).resolve().parents[5]
                    prior = os.environ.get('WORKBENCH_PROTOCOL_V3_PRIOR_PROBE_RECEIPT')
                    receipt = Path(prior).expanduser() if prior else root / 'runs/mw_protocol_v3_1r6_glm_transport_20260905/product_probe_attempt.json'
                    budget = int(os.environ.get('WORKBENCH_PROTOCOL_V3_MAX_INPUT_BYTES', '2000000'))
                    factory = create_product_design_elements_factory(storage_config=storage_config,
                        prior_probe_receipt=receipt, max_input_bytes=budget,
                        product_profile=resolve_product_profile())
        return factory(project_id)
    return resolve


def _profile_transport(profile: str, *, credential_resolver, http_opener):
    """Per-profile (roles, adapter factory partial) for the shared dispatch."""
    bindings = profile_bindings(profile)
    if profile == 'deepseek':
        adapter = partial(build_deepseek_api_adapter,
                          credential_resolver=bindings['credential_resolver'],
                          http_opener=http_opener)
    else:
        adapter = partial(build_zhipu_api_adapter,
                          credential_resolver=credential_resolver,
                          http_opener=http_opener)
    return bindings, adapter
