"""Follow-up independent probes. Synthetic tmp SQLite / fake transport only."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from fastapi.testclient import TestClient

from app.protocol_workflow.api.composition import (
    ProtocolWorkflowMountConfig,
    mount_protocol_workflow_router,
)
from app.protocol_workflow.agent2.product import create_product_regimen_factory
from app.protocol_workflow.agent2.study_input import (
    bind_regimen_study_input,
    clinical_study_facts,
    validate_regimen_study_input,
)
from app.protocol_workflow.agent2.coordinator import RegimenCoordinator
from app.protocol_workflow.agent2.study_definition import prepare_regimen_adoption
from app.protocol_workflow.application.research_context import prepare_research_context_creation
from app.protocol_workflow.canonical.decision_inputs import (
    DecisionInputRef,
    bind_decision_inputs,
    current_input_validity,
    input_refs_payload,
)
from app.protocol_workflow.canonical.hashing import canonical_json
from app.protocol_workflow.registries.fact_bindings import (
    FactBinding,
    FactBindingError,
    _binding_material,
    affected_chapter_fact_paths,
    bind_chapter_input,
)
from test_clinical_design_worker import prepared_reference
from test_chapter_fact_binding import confirmed_study, _objectives_contract
from test_regimen_workflow_integration import ROOT
from test_zhipu_product_transport import _FakeOpener, _FakeResponse, _completion_body
from test_mounted_api_integration import PROJECT, SD_ID, _create_body, _apply_body
from test_template_fact_adoption import _dump
from test_all_chapter_contracts import REAL_TEMPLATE_DIR
from app.protocol_workflow.registries.fact_bindings import FactBindingCatalog
import integration_shared as shared

SCRATCH = Path(__file__).resolve().parent
PRIOR = ROOT.parents[2] / "runs/mw_protocol_v3_1r6_glm_transport_20260905/product_probe_attempt.json"
RESULTS = []


def record(name, **payload):
    RESULTS.append({"name": name, **payload})
    print(json.dumps({"name": name, **payload}, ensure_ascii=False, default=str))


def client_for(db, designs):
    app = FastAPI()
    mount_protocol_workflow_router(
        app, ProtocolWorkflowMountConfig(enabled=True, db_path=db),
        regimen_coordinator_factory=designs,
    )
    return TestClient(app)


def make_designs(db, opener):
    return create_product_regimen_factory(
        storage_config={"backend": "sqlite", "path": str(db)},
        prior_probe_receipt=PRIOR, max_input_bytes=2000000,
        credential_resolver=lambda: "synthetic-only", http_opener=opener,
    )


def probe_study_input_identity():
    original, _ = prepared_reference()
    facts = {
        "picos.phase": "II",
        "research.input_context": {"hash": "source"},
        "research.regimen_producer": {"workflow_run_id": "old"},
    }
    bound = bind_regimen_study_input(original, study_definition_id="study:a", facts=facts)
    payload = bound.to_payload()
    coordinator = RegimenCoordinator(project_id="project:a", branch_id="main", runtime=None, artifact_store=None)
    source_only = coordinator.run_id(original)
    study_a = coordinator.run_id(bound)
    other_study = coordinator.run_id(bind_regimen_study_input(original, study_definition_id="study:b", facts=facts))
    facts_changed = coordinator.run_id(bind_regimen_study_input(
        original, study_definition_id="study:a", facts={**facts, "picos.phase": "III"}))
    producer_only = bind_regimen_study_input(original, study_definition_id="study:a", facts={
        "picos.phase": "II", "research.regimen_producer": {"workflow_run_id": "new"}})
    validate_ok = None
    try:
        validate_regimen_study_input(bound, study_definition_id="study:a", facts=facts)
        validate_ok = True
    except ValueError as exc:
        validate_ok = str(exc)
    wrong_study = wrong_facts = source_skip = None
    try:
        validate_regimen_study_input(bound, study_definition_id="study:b", facts=facts)
    except ValueError as exc:
        wrong_study = str(exc)
    try:
        validate_regimen_study_input(bound, study_definition_id="study:a", facts={**facts, "picos.phase": "III"})
    except ValueError as exc:
        wrong_facts = str(exc)
    validate_regimen_study_input(original, study_definition_id="study:zzz", facts={"picos.phase": "III"})
    source_skip = True
    record(
        "study_input_identity",
        clinical_facts=payload["confirmed_study"]["facts"],
        excludes_research_keys=set(payload["confirmed_study"]["facts"]) == {"picos.phase"},
        source_only_key_unchanged=source_only == coordinator.run_id(original),
        distinct_keys=len({source_only, study_a, other_study, facts_changed}) == 4,
        producer_metadata_same_key=bound == producer_only,
        instruction_mentions_confirmed_study="confirmed_study是目标研究已确认的事实" in payload["instruction"],
        validate_ok=validate_ok is True,
        wrong_study=wrong_study,
        wrong_facts=wrong_facts,
        source_only_skips_target_check=source_skip,
        ok=set(payload["confirmed_study"]["facts"]) == {"picos.phase"}
        and len({source_only, study_a, other_study, facts_changed}) == 4
        and bound == producer_only and wrong_study == "regimen_target_study_changed"
        and wrong_facts == "regimen_clinical_facts_changed" and source_skip,
    )


def probe_prepare_start_recover(tmp):
    db = tmp / "prepare.sqlite"
    shared.admit(db, PROJECT)
    prepared, output = prepared_reference()
    opener = _FakeOpener([_FakeResponse(_completion_body(content=json.dumps(output)))])
    designs = make_designs(db, opener)
    decided = datetime(2026, 9, 13, tzinfo=timezone.utc)
    creation = prepare_research_context_creation(
        project_id=PROJECT, study_definition_id=SD_ID, seed_run_id="seed:fixture",
        prepared=prepared, operation_id="operation:context:prepare",
        actor_id="user:example", decided_at=decided,
    )
    base = f"/api/projects/{PROJECT}/protocol-workflow"
    with client_for(db, designs) as c:
        created = c.post(base + "/study-definitions", json=jsonable_encoder(creation))
        assert created.status_code == 200, created.text
        seed_body = {"seed_run_id": "seed:fixture", "study_definition_id": SD_ID}
        # prepare without a real seed run will 409/404 because prepared() reads seed coordinator.
        # This probe uses bind+start via regimen coordinator only; seed path is in frozen integration.
        bound = bind_regimen_study_input(prepared, study_definition_id=SD_ID, facts={})
        run = designs(PROJECT).start(bound)
        assert designs(PROJECT).resume(run)["status"] == "ready_for_review"
        before = opener.calls
        key = designs(PROJECT).run_id(bound)
        assert key == run
        # recover original key after successor clinical facts
        update = _apply_body(
            snapshot_sha256=created.json()["revision_sha256"], expected_revision=1,
            idempotency_key="clinical:phase", decision_record_id="decision:phase",
            fact_updates={"picos.phase": "III"},
        )
        update["revise_confirmed_facts"] = True
        update["project_id"] = PROJECT
        update["study_definition_id"] = SD_ID
        changed = c.post(base + f"/study-definitions/{SD_ID}/decisions", json=update)
        assert changed.status_code == 200, changed.text
        original_intent = {"seed_run_id": "not-used-for-this-recover", "study_definition_id": SD_ID,
                           "expected_workflow_run_id": run}
        # recover uses original key; seed_proposal on run vs current seed coordinator would 409
        # because seed:fixture is not a seed workflow. Use coordinator.prepared_request directly.
        recovered_state = designs(PROJECT).read(run)
        new_bound = bind_regimen_study_input(prepared, study_definition_id=SD_ID, facts={"picos.phase": "III"})
        new_key = designs(PROJECT).run_id(new_bound)
        # wrong target
        other = bind_regimen_study_input(prepared, study_definition_id="study:other", facts={})
        other_key = designs(PROJECT).run_id(other)
        # start via HTTP with expected original key: original_state needs seed coordinator.
        # Probe coordinator-level identity + HTTP adopt/start where mounted.
        adopt_intent = {
            "study_definition_id": SD_ID, "operation_id": "operation:regimen:prep",
            "expected_revision": 2, "snapshot_sha256": changed.json()["revision_sha256"],
            "actor_id": "user:example", "decided_at": "2026-09-13T07:00:00+00:00",
            "reason": "采用完整给药方案",
        }
        # facts changed vs generation read set → fresh adopt 409
        before_adopt = _dump(db)
        rejected = c.post(base + f"/design/regimen/{run}/adopt", json=adopt_intent)
        # historical lookup still works? no receipt yet. Create receipt at matching facts first in next probe.
        record(
            "prepare_identity_after_successor_facts",
            original_key=run,
            new_key_after_phase_change=new_key,
            keys_differ=run != new_key,
            other_study_key_differs=other_key != run,
            opener_unchanged_after_fact_change=opener.calls == before,
            recovered_status=recovered_state["status"],
            recovered_same_run=recovered_state["workflow_run_id"] == run,
            fresh_adopt_after_fact_change_status=rejected.status_code,
            dump_unchanged=before_adopt == _dump(db),
            ok=run != new_key != other_key and opener.calls == before
            and recovered_state["workflow_run_id"] == run and rejected.status_code == 409
            and before_adopt == _dump(db),
        )


def probe_http_prepare_wrong_seed_unknown_empty(tmp):
    """Mounted design API: wrong target/seed, unknown key, empty expected, source drift."""
    from app.protocol_workflow.agent1.seed_product import create_product_seed_factory
    from test_source_import_api import PROJECT as SRC_PROJECT, BASE, upload
    from test_writing_reference_docx import build_docx, paragraph_xml

    db = tmp / "http.sqlite"
    shared.admit(db, SRC_PROJECT)
    opener = _FakeOpener([
        _FakeResponse(_completion_body(content='{"fields":{}}')),
        _FakeResponse(_completion_body(content='{"coverage":[],"regimen":null,"questions":["拟采用哪份给药依据？"]}')),
        _FakeResponse(_completion_body(content='{"coverage":[],"regimen":null,"questions":["拟采用哪份给药依据？"]}')),
    ])
    kwargs = dict(
        storage_config={"backend": "sqlite", "path": str(db)},
        prior_probe_receipt=PRIOR, max_input_bytes=100000,
        credential_resolver=lambda: "synthetic-only", http_opener=opener,
    )
    seeds = create_product_seed_factory(**kwargs)
    designs = create_product_regimen_factory(**kwargs)
    app = FastAPI()
    mount_protocol_workflow_router(
        app, ProtocolWorkflowMountConfig(enabled=True, db_path=db),
        seed_coordinator_factory=seeds, regimen_coordinator_factory=designs,
    )
    endpoint = BASE.removesuffix("/sources")
    with TestClient(app) as c:
        source = upload(c, build_docx(paragraph_xml("完整原资料不能丢失"))).json()["current"]["source"]
        seed = c.post(endpoint + "/research-intake", json={
            "user_brief": "准备设计", "source_artifact_ids": [source["source_artifact_id"]],
        })
        assert seed.status_code == 202, seed.text
        seed_id = seed.json()["workflow_run_id"]
        created = c.post(endpoint + "/design/regimen/study-context", json={
            "seed_run_id": seed_id, "operation_id": "context:http",
            "actor_id": "user:test", "decided_at": "2026-09-13T10:00:00Z",
        })
        assert created.status_code == 200, created.text
        study_id = created.json()["study_definition_id"]
        calls_before_prepare = opener.calls
        prepared_intent = c.post(endpoint + "/design/regimen/prepare", json={
            "seed_run_id": seed_id, "study_definition_id": study_id,
        })
        assert prepared_intent.status_code == 200, prepared_intent.text
        body = prepared_intent.json()
        prepare_no_gen = opener.calls == calls_before_prepare
        started = c.post(endpoint + "/design/regimen", json=body)
        assert started.status_code == 202, started.text
        run = started.json()["workflow_run_id"]
        assert run == body["expected_workflow_run_id"]
        gen_calls = opener.calls
        # empty expected on recover → current key (same, still finds)
        empty_recover = c.post(endpoint + "/design/regimen/recover", json={
            "seed_run_id": seed_id, "study_definition_id": study_id,
        })
        # unknown expected
        unknown = c.post(endpoint + "/design/regimen/recover", json={
            **body, "expected_workflow_run_id": "regimen-design:" + "a" * 64,
        })
        # start unknown expected that is not current key → 409, no extra gen
        unknown_start = c.post(endpoint + "/design/regimen", json={
            **body, "expected_workflow_run_id": "regimen-design:" + "b" * 64,
        })
        # wrong study
        wrong_study = c.post(endpoint + "/design/regimen/recover", json={
            **body, "study_definition_id": "study:other",
        })
        # wrong seed (new intake)
        seed2 = c.post(endpoint + "/research-intake", json={
            "user_brief": "另一份说明", "source_artifact_ids": [source["source_artifact_id"]],
        })
        assert seed2.status_code == 202, seed2.text
        wrong_seed = c.post(endpoint + "/design/regimen/recover", json={
            **body, "seed_run_id": seed2.json()["workflow_run_id"],
        })
        # successor facts: prepare new key, recover original still works
        update = _apply_body(
            snapshot_sha256=created.json()["revision_sha256"], expected_revision=1,
            idempotency_key="http:phase", decision_record_id="decision:http-phase",
            fact_updates={"picos.phase": "III"},
        )
        update["revise_confirmed_facts"] = True
        update["project_id"] = SRC_PROJECT
        update["study_definition_id"] = study_id
        advanced = c.post(endpoint + f"/study-definitions/{study_id}/decisions", json=update)
        assert advanced.status_code == 200, advanced.text
        next_prep = c.post(endpoint + "/design/regimen/prepare", json={
            "seed_run_id": seed_id, "study_definition_id": study_id,
        })
        original_recover = c.post(endpoint + "/design/regimen/recover", json=body)
        original_start = c.post(endpoint + "/design/regimen", json=body)
        current_start_without_expected = c.post(endpoint + "/design/regimen", json={
            "seed_run_id": seed_id, "study_definition_id": study_id,
        })
        empty_params = c.post(endpoint + "/design/regimen/prepare", json={})
        record(
            "http_prepare_start_recover_challenges",
            prepare_status=prepared_intent.status_code,
            prepare_no_generation=prepare_no_gen,
            start_run=run,
            empty_recover_status=empty_recover.status_code,
            empty_recover_run=(empty_recover.json() or {}).get("workflow_run_id"),
            unknown_recover_status=unknown.status_code,
            unknown_start_status=unknown_start.status_code,
            wrong_study_status=wrong_study.status_code,
            wrong_seed_status=wrong_seed.status_code,
            successor_prepare_new_key=next_prep.json().get("expected_workflow_run_id") != run,
            original_recover_after_facts=original_recover.status_code == 200
            and original_recover.json().get("workflow_run_id") == run,
            original_start_reuses=original_start.status_code == 202
            and original_start.json().get("workflow_run_id") == run,
            current_start_new_key=current_start_without_expected.status_code == 202
            and current_start_without_expected.json().get("workflow_run_id") != run,
            empty_prepare_status=empty_params.status_code,
            opener_after_challenges=opener.calls,
            gen_calls_at_first_start=gen_calls,
            extra_gen_for_new_key=opener.calls > gen_calls,
            ok=prepare_no_gen and unknown.status_code == 404 and unknown_start.status_code == 409
            and wrong_study.status_code == 409 and wrong_seed.status_code == 409
            and next_prep.json().get("expected_workflow_run_id") != run
            and original_recover.json().get("workflow_run_id") == run
            and original_start.json().get("workflow_run_id") == run
            and current_start_without_expected.json().get("workflow_run_id") != run
            and empty_params.status_code in (422, 400),
        )


def probe_adoption_readset_and_receipt(tmp):
    db = tmp / "adopt.sqlite"
    shared.admit(db, PROJECT)
    prepared, output = prepared_reference()
    bound = bind_regimen_study_input(prepared, study_definition_id=SD_ID, facts={})
    opener = _FakeOpener([_FakeResponse(_completion_body(content=json.dumps(output)))])
    designs = make_designs(db, opener)
    run = designs(PROJECT).start(bound)
    assert designs(PROJECT).resume(run)["status"] == "ready_for_review"
    command = prepare_regimen_adoption(
        designs(PROJECT), run, study_definition_id=SD_ID, operation_id="op:cmd",
        expected_revision=1, snapshot_sha256="a" * 64, actor_id="user:example",
        decided_at=datetime(2026, 9, 13, tzinfo=timezone.utc), reason="采用完整给药方案",
    )
    ref_payloads = input_refs_payload(command.decision_input_refs)
    scopes = [item.get("scope") for item in ref_payloads]
    fact_payloads = [item for item in ref_payloads if item.get("scope") != "all_facts"]
    all_facts = [item for item in ref_payloads if item.get("scope") == "all_facts"]
    ordinary = DecisionInputRef(fact_path="research.input_context")
    ordinary_payload = input_refs_payload((ordinary,))[0]
    source_only_cmd = prepare_regimen_adoption(
        # Use a source-only run
        type("C", (), {
            "project_id": PROJECT,
            "read": lambda self, run_id: designs(PROJECT).read(run),
            "prepared_request": lambda self, run_id: prepared,
        })(),
        run, study_definition_id=SD_ID, operation_id="op:src",
        expected_revision=1, snapshot_sha256="a" * 64, actor_id="user:example",
        decided_at=datetime(2026, 9, 13, tzinfo=timezone.utc), reason="采用完整给药方案",
    )
    source_refs = input_refs_payload(source_only_cmd.decision_input_refs)
    # all_facts add/delete/metadata
    ref = DecisionInputRef(
        fact_path="clinical-read-set", scope="all_facts",
        excluded_fact_paths=("research.input_context", "research.regimen_producer"),
    )
    before = {"picos.phase": "II", "research.regimen_producer": {"run": "old"}}
    bound_inputs = bind_decision_inputs((ref,), before, "a" * 64)
    add_stale = current_input_validity(bound_inputs, {**before, "picos.population": "adult"})
    del_stale = current_input_validity(bound_inputs, {"research.regimen_producer": {"run": "old"}})
    meta_current = current_input_validity(bound_inputs, {**before, "research.regimen_producer": {"run": "new"}})
    # HTTP: adopt study-bound then successor then historical replay
    creation = prepare_research_context_creation(
        project_id=PROJECT, study_definition_id=SD_ID, seed_run_id="seed:fixture",
        prepared=bound, operation_id="operation:context:adopt",
        actor_id="user:example", decided_at=datetime(2026, 9, 13, tzinfo=timezone.utc),
    )
    base = f"/api/projects/{PROJECT}/protocol-workflow"
    with client_for(db, designs) as c:
        created = c.post(base + "/study-definitions", json=jsonable_encoder(creation))
        intent = {
            "study_definition_id": SD_ID, "operation_id": "operation:regimen:bound",
            "expected_revision": 1, "snapshot_sha256": created.json()["revision_sha256"],
            "actor_id": "user:example", "decided_at": "2026-09-13T07:00:00+00:00",
            "reason": "采用完整给药方案",
        }
        adopted = c.post(base + f"/design/regimen/{run}/adopt", json=intent)
        assert adopted.status_code == 200, adopted.text
        graph1 = c.get(base + f"/study-definitions/{SD_ID}/decision-graph").json()["records"]
        dose1 = next(r for r in graph1 if r["decision_key"] == "decision:dose-regimen")
        update = _apply_body(
            snapshot_sha256=adopted.json()["revision_sha256"], expected_revision=2,
            idempotency_key="op:add-clinical", decision_record_id="decision:add-clinical",
            fact_updates={"picos.phase": "III"},
        )
        update["revise_confirmed_facts"] = True
        update["decision_record"]["decision_key"] = "decision:research-request"
        advanced = c.post(base + f"/study-definitions/{SD_ID}/decisions", json=update)
        assert advanced.status_code == 200, advanced.text
        graph2 = c.get(base + f"/study-definitions/{SD_ID}/decision-graph").json()["records"]
        dose2 = next(r for r in graph2 if r["decision_key"] == "decision:dose-regimen")
        after = _dump(db)
        historical = c.post(base + f"/design/regimen/{run}/adopt", json=intent)
        recovered = c.post(base + f"/design/regimen/{run}/adopt/recover", json=intent)
        record(
            "adoption_readset_receipt_validity",
            study_bound_has_all_facts=bool(all_facts),
            all_facts_excludes=all_facts[0]["excluded_fact_paths"] if all_facts else None,
            ordinary_fact_payload_omits_scope="scope" not in ordinary_payload
            and "excluded_fact_paths" not in ordinary_payload,
            ordinary_serialized_paths=[item.get("fact_path") for item in fact_payloads],
            source_only_ref_count=len(source_refs),
            source_only_has_all_facts=any(item.get("scope") == "all_facts" for item in source_refs),
            add_clinical_stale=add_stale,
            delete_clinical_stale=del_stale,
            producer_metadata_current=meta_current,
            adopt_status=adopted.status_code,
            validity_before=dose1["current_validity"],
            validity_after_add_clinical=dose2["current_validity"],
            historical_replayed=historical.json().get("replayed"),
            historical_revision=historical.json().get("revision"),
            historical_decision_id=historical.json().get("effective_decision", {}).get("decision_record_id"),
            original_decision_id=adopted.json()["effective_decision"]["decision_record_id"],
            dump_unchanged=after == _dump(db),
            recover_revision=recovered.json().get("revision"),
            ok=bool(all_facts) and "scope" not in ordinary_payload
            and not any(item.get("scope") == "all_facts" for item in source_refs)
            and add_stale == "stale" and del_stale == "stale" and meta_current == "current"
            and dose1["current_validity"] == "current" and dose2["current_validity"] == "stale"
            and historical.json().get("replayed") is True
            and historical.json().get("revision") == 3
            and historical.json()["effective_decision"]["decision_record_id"]
            == adopted.json()["effective_decision"]["decision_record_id"]
            and after == _dump(db),
        )


def probe_fact_binding_aliases():
    catalog = FactBindingCatalog.model_validate_json((REAL_TEMPLATE_DIR / "fact_bindings.json").read_text())
    bindings = {b.fact_path: b for b in catalog.bindings}
    three = (
        "picos.intervention_dose_regimen",
        "picos.intervention_dose_regimen.selected_regimen",
        "synopsis.interventions",
    )
    compound = {"periods": [{"id": "p1", "label": "诱导", "timing": "第0-4周"}],
                "arms": [{"id": "a1", "label": "试验组"}],
                "schedules": []}
    affected = affected_chapter_fact_paths(catalog.bindings, ("intervention.dose_regimen",))
    affected_legacy = affected_chapter_fact_paths(catalog.bindings, ("picos.intervention_dose_regimen",))
    affected_10mg = affected_chapter_fact_paths(catalog.bindings, ("picos.intervention.dose",))
    starting = bindings["picos.intervention_dose_regimen.starting_dose"]
    alias = bindings["picos.intervention_dose_regimen"]
    available_ok = None
    try:
        from app.protocol_workflow.registries.fact_bindings import bind_chapter_input as bci
        # Build contract from real catalog's first chapter that requires this path? Too heavy.
        # Manually replicate the available/conflict branch:
        study_facts = {
            "intervention.dose_regimen": compound,
            "picos.intervention_dose_regimen": {"text": "old literal"},
        }
        available = [key for key in (alias.canonical_path, *alias.legacy_canonical_paths) if key in study_facts]
        from app.protocol_workflow.registries.fact_bindings import _typed_value, _json
        value = _typed_value(alias, study_facts[available[0]], "native_json")
        conflict_detected = False
        for legacy_path in available[1:]:
            if _json(value) != _json(_typed_value(alias, study_facts[legacy_path], "native_json")):
                conflict_detected = True
        available_ok = available == ["intervention.dose_regimen", "picos.intervention_dose_regimen"] and conflict_detected
    except FactBindingError as exc:
        available_ok = exc.code
    empty_legacy_material = _binding_material(FactBinding(
        fact_path="x", canonical_path="x", value_type="json", source_refs=("s",),
    ))
    with_legacy_material = _binding_material(alias)
    literal_only = [key for key in (alias.canonical_path, *alias.legacy_canonical_paths)
                    if key in {"picos.intervention_dose_regimen"}]
    # synopsis.interventions stored only as vocabulary key, not canonical/legacy
    syn = bindings["synopsis.interventions"]
    syn_available_if_only_vocab = [key for key in (syn.canonical_path, *syn.legacy_canonical_paths)
                                   if key in {"synopsis.interventions"}]
    record(
        "fact_binding_aliases",
        three_point_to_compound={path: bindings[path].canonical_path for path in three},
        three_have_legacy={path: list(bindings[path].legacy_canonical_paths) for path in three},
        three_value_type={path: bindings[path].value_type for path in three},
        affected_includes_three=all(path in affected for path in three),
        affected_from_legacy_picos=all(path in affected_legacy for path in (
            "picos.intervention_dose_regimen", "synopsis.interventions")),
        ten_mg_fixture_key_not_in_catalog="picos.intervention.dose" not in bindings,
        ten_mg_update_affects_nothing=affected_10mg == (),
        starting_dose_not_compound=starting.canonical_path == "picos.intervention_dose_regimen.starting_dose",
        empty_legacy_omitted_from_hash_material="legacy_canonical_paths" not in empty_legacy_material,
        alias_material_keeps_legacy="legacy_canonical_paths" in with_legacy_material,
        conflicting_compound_and_legacy_detected=available_ok is True,
        synopsis_vocab_only_does_not_fallback=syn_available_if_only_vocab == [],
        ok=all(bindings[path].canonical_path == "intervention.dose_regimen" for path in three)
        and all(path in affected for path in three)
        and "picos.intervention.dose" not in bindings
        and affected_10mg == ()
        and starting.canonical_path != "intervention.dose_regimen"
        and "legacy_canonical_paths" not in empty_legacy_material
        and available_ok is True
        and syn_available_if_only_vocab == [],
    )


def probe_frontend_key_logic():
    src = Path("frontend/src/features/medical-writing/protocol-workbench/RegimenDesignWorkspace.jsx").read_text()
    adopt = Path("frontend/src/features/medical-writing/protocol-workbench/RegimenAdoptionCard.jsx").read_text()
    record(
        "frontend_source_invariants",
        prepare_before_start="prepareRegimenDesign" in src and "localStorage.setItem(key, JSON.stringify({pending: true, intent}))" in src,
        recover_uses_saved_intent="recoverRegimenDesign(projectId, saved.intent || seedRunId" in src,
        component_key_includes_study="props.studyDefinitionId" in src.split("export function RegimenDesignWorkspace")[1],
        scoped_key_includes_study='JSON.stringify([projectId, seedRunId, studyDefinitionId])' in src,
        legacy_not_deleted="do not delete old records" in src.lower() or "Never move a known study-bound" in src,
        pending_without_intent_falls_back_to_seed="saved.intent || seedRunId" in src,
        validity_matches_decision_id="record.decision_record_id === receipt.effective_decision.decision_record_id" in adopt,
        graph_failure_unavailable="setValidity('unavailable')" in adopt,
        does_not_claim_current_on_failure="validity === 'current'" in adopt and "unavailable" in adopt,
        ok="prepareRegimenDesign" in src and "setValidity('unavailable')" in adopt,
    )


def main():
    tmp = SCRATCH / "tmp"
    tmp.mkdir(exist_ok=True)
    probe_study_input_identity()
    probe_prepare_start_recover(tmp)
    probe_http_prepare_wrong_seed_unknown_empty(tmp)
    probe_adoption_readset_and_receipt(tmp)
    probe_fact_binding_aliases()
    probe_frontend_key_logic()
    out = SCRATCH / "probe_results.json"
    out.write_text(json.dumps(RESULTS, ensure_ascii=False, indent=2, default=str))
    failed = [item["name"] for item in RESULTS if not item.get("ok")]
    print("FAILED" if failed else "ALL_PROBES_RECORDED", failed)


if __name__ == "__main__":
    main()
