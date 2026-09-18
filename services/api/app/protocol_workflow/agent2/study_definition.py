"""Prepare canonical fact proposals; existing application owns human adoption."""
from copy import deepcopy
from .clinical_worker import RegimenProposal


#: Server-side medical validity scope of the dose-regimen confirmation card.
#: Deliberately narrower than the producer read-set: only facts the user's
#: dose decision medically depends on reopen this card, each with an explicit
#: rationale. The producer's all_facts binding stays recorded for production
#: reconciliation but no longer drives the user-facing validity.
REGIMEN_CONFIRMATION_DEPENDENCIES = (
    {
        "fact_path": "framing.study_phase",
        "rationale": "研究期别决定给药设计的监管框架与常规剂量策略，期别变化时既有剂量建议需重新医学评估。",
    },
    {
        "fact_path": "picos.population_summary",
        "rationale": "目标人群特征（成人/儿童、器官功能范围等）直接影响剂量的适用性与安全性，人群定义变化需重新确认。",
    },
    {
        "fact_path": "synopsis.interventions",
        "rationale": "研究药物身份（活性成分/制剂）是剂量建议的前提，药物本身变化时原剂量不可沿用。",
    },
)


def prepare_regimen_adoption(coordinator, run_id, *, study_definition_id, operation_id,
                            expected_revision, snapshot_sha256, actor_id, decided_at, reason):
    """Translate explicit user intent into the existing atomic application command.

    The operation id and timestamp belong to the original persisted UI intent;
    rebuilding a lost acknowledgement keeps the same decision material. The
    current study CAS and historical exact replay are owned by ApplicationService.
    No scientific rationale or evidence admission is invented here.
    """
    from app.protocol_workflow.application import ApplyStudyDecisionCommand
    from app.protocol_workflow.application.commands import TemplateAdoptionIntent
    from app.protocol_workflow.canonical.decision_inputs import DecisionInputRef
    from packages.contracts.workbench_contracts.protocol_v3 import ActorType

    state = coordinator.read(run_id)
    validation = state.get("validation")
    if state.get("status") != "ready_for_review" or not validation or validation.get("valid") is not True:
        raise ValueError("regimen_information_unresolved")
    updates = propose_regimen_fact_updates(validation["proposal"])
    output_sha = validation["raw_response"]["output_sha256"]
    from .input_context import regimen_input_context
    prepared = coordinator.prepared_request(run_id)
    context = regimen_input_context(prepared)
    updates["research.regimen_producer"] = {
        "workflow_run_id": run_id, "input_sha256": prepared.input_sha256,
        "output_sha256": output_sha, "source_context": context,
    }
    decision = _regimen_decision_record(coordinator.project_id, run_id, output_sha,
        study_definition_id=study_definition_id, operation_id=operation_id,
        expected_revision=expected_revision, snapshot_sha256=snapshot_sha256,
        actor_id=actor_id, decided_at=decided_at, reason=reason)
    refs = (DecisionInputRef(fact_path="intervention.dose_regimen"),
            DecisionInputRef(fact_path="research.input_context"),
            DecisionInputRef(fact_path="research.regimen_producer"))
    if "confirmed_study" in prepared.to_payload():
        # This producer actually received the entire clinical fact dictionary.
        # Track its key set too: newly added study facts may invalidate it.
        refs += (DecisionInputRef(fact_path="clinical-read-set", scope="all_facts",
            excluded_fact_paths=("research.input_context", "research.regimen_producer")),)
    return ApplyStudyDecisionCommand(project_id=coordinator.project_id, study_definition_id=study_definition_id,
        idempotency_key=operation_id, expected_revision=expected_revision, actor_type=ActorType.USER,
        actor_id=actor_id, reason=reason, decision_record=decision, fact_updates=updates,
        revise_confirmed_facts=True, template_adoption=TemplateAdoptionIntent(template_id="tp_ma_07_v2"),
        decision_input_refs=refs,
        confirmation_dependencies=REGIMEN_CONFIRMATION_DEPENDENCIES)


def propose_regimen_fact_updates(proposal: dict) -> dict:
    """Build one compound fact, without confirming it or writing any storage.

    The caller must use the persisted, validated design result. This helper is
    not a replacement for its provenance check, explicit human decision, current
    snapshot CAS, template adoption, or downstream impact calculation.
    """
    if proposal.get("status") != "ready_for_review" or proposal.get("questions"):
        raise ValueError("regimen_information_unresolved")
    raw = deepcopy(proposal.get("regimen"))
    if not isinstance(raw, dict):
        raise ValueError("regimen_information_unresolved")
    # These two annotations are server-added source/display metadata, not
    # model fields or dosage facts. Preserve citations in the canonical value.
    for schedule in raw.get("schedules", []):
        for step in schedule.get("steps", []):
            step.pop("source_support", None)
            step.pop("requires_confirmation", None)
    regimen = RegimenProposal.model_validate(raw)
    if regimen.unresolved_questions or any(item.get("relation") == "unresolved" for item in proposal.get("coverage", [])):
        raise ValueError("regimen_information_unresolved")
    value = regimen.model_dump(mode="json", exclude={"canonical_state", "input_sha256", "unresolved_questions"})
    return {"intervention.dose_regimen": value}


def _regimen_decision_record(project_id, run_id, output_sha, *, study_definition_id,
                             operation_id, expected_revision, snapshot_sha256,
                             actor_id, decided_at, reason):
    import hashlib
    from app.protocol_workflow.canonical.hashing import canonical_json
    from packages.contracts.workbench_contracts.protocol_v3 import ActorType, DecisionRecord
    option_id = "regimen-option:" + hashlib.sha256(canonical_json([run_id, output_sha]).encode()).hexdigest()
    record_id = "regimen-decision:" + hashlib.sha256(canonical_json(
        [project_id, study_definition_id, operation_id]).encode()).hexdigest()
    decision = DecisionRecord(decision_record_id=record_id, decision_key="decision:dose-regimen",
        snapshot_sha256=snapshot_sha256, expected_state_revision=expected_revision,
        state_revision=expected_revision+1, option_ids=(option_id,), selected_option_id=option_id,
        actor_type=ActorType.USER, actor_id=actor_id, reason=reason, decided_at=decided_at)
    return decision


def prepare_regimen_recovery(coordinator, run_id, **intent):
    """Use the immutable output identity, not current readiness or fact compilation."""
    from app.protocol_workflow.application.queries import RecoverStudyDecisionQuery
    state = coordinator.read(run_id)
    output_sha = ((state.get("validation") or {}).get("raw_response") or {}).get("output_sha256")
    if not output_sha:
        return None
    record = _regimen_decision_record(coordinator.project_id, run_id, output_sha, **intent)
    return RecoverStudyDecisionQuery(project_id=coordinator.project_id,
        study_definition_id=intent["study_definition_id"], idempotency_key=intent["operation_id"],
        decision_record=record)
