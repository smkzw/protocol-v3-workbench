"""Product chapter transport binding; credentials are resolved only on execution."""
from functools import partial
from app.protocol_workflow.artifacts.local_store import LocalArtifactStore
from app.protocol_workflow.registries import load_skill_registry
from app.protocol_workflow.runtime.product_profiles import select_role_registry_document, default_role_registry_path
from app.protocol_workflow.runtime.product_profile_bindings import select_profile_roles
from app.protocol_workflow.runtime.harness import HarnessDispatcher
from app.protocol_workflow.runtime.restored_probe import RestoredZhipuProbePolicy
from app.protocol_workflow.runtime.omp_credentials import resolve_omp_zhipu_key
from app.protocol_workflow.runtime.product_profile_bindings import resolve_product_profile
from app.protocol_workflow.runtime.adapters.zhipu_api import build_zhipu_api_adapter
from app.protocol_workflow.runtime.adapters.deepseek_api import build_deepseek_api_adapter
from app.protocol_workflow.storage.sqlite import build_unit_of_work_factory, build_committed_reservation_repository_factory
from .subgraph import build_chapter_draft_runtime
from .coordinator import ChapterDraftCoordinator


def create_product_chapter_factory(*, storage_config, prior_probe_receipt,
                                   max_input_bytes, credential_resolver=resolve_omp_zhipu_key,
                                   http_opener=None, product_profile: str = 'glm'):
    if isinstance(max_input_bytes, bool) or not isinstance(max_input_bytes, int) or max_input_bytes <= 0:
        raise ValueError('chapter_product_input_budget_required')
    config = dict(storage_config)
    if product_profile == 'deepseek':
        roles = select_profile_roles('deepseek')
        role = next(role for role in roles.roles
                    if role.role_id == 'product-llm' and role.role_kind == 'llm')
        skills = load_skill_registry(default_role_registry_path().with_name('skill_registry.json'))
        skill = next(skill for skill in skills.skill_definitions()
                     if skill.skill_definition_id == 'skill.chapter-draft')
        dispatcher = HarnessDispatcher()
        adapter = partial(build_deepseek_api_adapter, http_opener=http_opener,
                          max_input_bytes=max_input_bytes)
    else:
        role = next(role for role in select_role_registry_document().roles
                    if role.role_id == 'product-llm' and role.role_kind == 'llm')
        skills = load_skill_registry(default_role_registry_path().with_name('skill_registry.json'))
        skill = next(skill for skill in skills.skill_definitions()
                     if skill.skill_definition_id == 'skill.chapter-draft')
        dispatcher = HarnessDispatcher(probe_policy=RestoredZhipuProbePolicy(prior_probe_receipt))
        adapter = partial(build_zhipu_api_adapter, credential_resolver=credential_resolver,
                          http_opener=http_opener, max_input_bytes=max_input_bytes)

    def factory(project_id, study_definition_id, study_revision_sha256):
        store = LocalArtifactStore(str(config['path']) + '.artifacts')
        runtime = build_chapter_draft_runtime(project_id=project_id,
            uow_factory=build_unit_of_work_factory(config),
            reservation_repository_factory=build_committed_reservation_repository_factory(config),
            artifact_store=store, role_entry=role, skill=skill,
            dispatcher=dispatcher, adapter_factory=adapter)
        return ChapterDraftCoordinator(project_id=project_id, branch_id='main',
            study_definition_id=study_definition_id, study_revision_sha256=study_revision_sha256,
            runtime=runtime, artifact_store=store, require_bound_input=True)
    return factory


def lazy_product_chapter_factory(storage_config):
    """Use existing product configuration only when a chapter is requested."""
    import os
    from pathlib import Path
    from threading import Lock
    lock = Lock()
    factory = None

    def resolve(project_id, study_definition_id, study_revision_sha256):
        nonlocal factory
        if factory is None:
            with lock:
                if factory is None:
                    root = Path(__file__).resolve().parents[5]
                    prior = os.environ.get('WORKBENCH_PROTOCOL_V3_PRIOR_PROBE_RECEIPT')
                    receipt = Path(prior).expanduser() if prior else root / 'runs/mw_protocol_v3_1r6_glm_transport_20260905/product_probe_attempt.json'
                    budget = int(os.environ.get('WORKBENCH_PROTOCOL_V3_MAX_INPUT_BYTES', '2000000'))
                    factory = create_product_chapter_factory(storage_config=storage_config,
                        prior_probe_receipt=receipt, max_input_bytes=budget,
                        product_profile=resolve_product_profile())
        return factory(project_id, study_definition_id, study_revision_sha256)
    return resolve
