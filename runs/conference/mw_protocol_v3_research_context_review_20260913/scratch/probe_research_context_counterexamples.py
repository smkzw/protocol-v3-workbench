"""Independent evidence probes: research context + source adoption chain.

Synthetic tmp SQLite / fake transport only. No product, live, or model writes.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.protocol_workflow.api.composition import (
    ProtocolWorkflowMountConfig,
    mount_protocol_workflow_router,
)
from app.protocol_workflow.agent1.seed_product import create_product_seed_factory
from app.protocol_workflow.agent2.product import create_product_regimen_factory
from app.protocol_workflow.agent2.input_context import regimen_input_context
from app.protocol_workflow.agent2.clinical_worker import PreparedRegimenRequest, prepare_regimen_request
from app.protocol_workflow.application.research_context import prepare_research_context_creation
from app.protocol_workflow.canonical.hashing import canonical_json
from test_clinical_design_worker import prepared_reference
from test_seed_workflow_integration import ROOT
from test_zhipu_product_transport import _FakeOpener, _FakeResponse, _completion_body
from test_source_import_api import PROJECT as SOURCE_PROJECT, BASE, upload
from test_writing_reference_docx import build_docx, paragraph_xml
from test_mounted_api_integration import PROJECT as API_PROJECT, SD_ID, _create_body
from test_template_fact_adoption import _dump
from test_clinical_design_worker import regimen
import integration_shared as shared

SCRATCH = Path(__file__).resolve().parent
PRIOR = ROOT.parents[2] / "runs/mw_protocol_v3_1r6_glm_transport_20260905/product_probe_attempt.json"
RESULTS = []


def record(name, **payload):
    RESULTS.append({"name": name, **payload})
    print(json.dumps({"name": name, **payload}, ensure_ascii=False, default=str))


def client_for(db, *, seeds=None, designs=None):
    app = FastAPI()
    mount_protocol_workflow_router(
        app,
        ProtocolWorkflowMountConfig(enabled=True, db_path=db),
        seed_coordinator_factory=seeds,
        regimen_coordinator_factory=designs,
    )
    return TestClient(app)


def make_seeds(db, opener):
    return create_product_seed_factory(
        storage_config={"backend": "sqlite", "path": str(db)},
        prior_probe_receipt=PRIOR,
        max_input_bytes=100000,
        credential_resolver=lambda: "synthetic-only",
        http_opener=opener,
    )


def make_designs(db, opener):
    return create_product_regimen_factory(
        storage_config={"backend": "sqlite", "path": str(db)},
        prior_probe_receipt=PRIOR,
        max_input_bytes=2000000,
        credential_resolver=lambda: "synthetic-only",
        http_opener=opener,
    )


def probe_source_identity_projection():
    prepared, _ = prepared_reference()
    context = regimen_input_context(prepared)
    payload = prepared.to_payload()
    source = payload["source_intake"]["sources"][0]
    listed_keys = set(context["source_artifacts"][0])
    omitted = sorted(set(source) - listed_keys)
    mutated = json.loads(prepared.payload_json)
    mutated["source_intake"]["sources"][0]["units"][0]["text"] += "（解析漂移）"
    mutated["seed_proposal"]["input_sha256"] = hashlib.sha256(
        canonical_json(mutated["source_intake"]).encode()
    ).hexdigest()
    text = canonical_json(mutated)
    drifted = PreparedRegimenRequest(text, hashlib.sha256(text.encode()).hexdigest())
    drifted_context = regimen_input_context(drifted)
    listed_same = context["source_artifacts"] == drifted_context["source_artifacts"]
    intake_differs = context["source_intake_sha256"] != drifted_context["source_intake_sha256"]
    record(
        "source_artifacts_omit_parse_identity",
        listed_keys=sorted(listed_keys),
        omitted_source_fields=omitted,
        listed_artifacts_unchanged_after_unit_drift=listed_same,
        intake_hash_changes_on_unit_drift=intake_differs,
        seed_hash_changes=context["seed_proposal_sha256"] != drifted_context["seed_proposal_sha256"],
        ok=listed_same and intake_differs and omitted != [],
    )


def probe_source_seed_mismatch_and_empty_sources():
    prepared, _ = prepared_reference()
    payload = prepared.to_payload()
    payload["source_intake"]["user_brief"] += " drift"
    text = canonical_json(payload)
    mismatched = PreparedRegimenRequest(text, hashlib.sha256(text.encode()).hexdigest())
    mismatch_error = None
    try:
        regimen_input_context(mismatched)
    except ValueError as exc:
        mismatch_error = str(exc)
    empty = json.loads(prepared.payload_json)
    empty["source_intake"]["sources"] = []
    empty["seed_proposal"]["input_sha256"] = hashlib.sha256(
        canonical_json(empty["source_intake"]).encode()
    ).hexdigest()
    empty_text = canonical_json(empty)
    empty_prepared = PreparedRegimenRequest(empty_text, hashlib.sha256(empty_text.encode()).hexdigest())
    empty_context = regimen_input_context(empty_prepared)
    record(
        "mismatch_and_empty_sources",
        mismatch_error=mismatch_error,
        empty_sources_accepted=empty_context["source_artifacts"] == [],
        empty_still_has_brief=bool(empty_context["user_brief"]),
        ok=mismatch_error == "source_input_identity_mismatch" and empty_context["source_artifacts"] == [],
    )


def probe_wrong_study_and_cross_study_same_context(tmp):
    db = tmp / "cross.sqlite"
    shared.admit(db, API_PROJECT)
    prepared, output = prepared_reference()
    opener = _FakeOpener([_FakeResponse(_completion_body(content=json.dumps(output)))])
    designs = make_designs(db, opener)
    run = designs(API_PROJECT).start(prepared)
    assert designs(API_PROJECT).resume(run)["status"] == "ready_for_review"
    context = regimen_input_context(prepared)
    decided = datetime(2026, 9, 13, tzinfo=timezone.utc)
    creation_a = prepare_research_context_creation(
        project_id=API_PROJECT, study_definition_id="study:alpha",
        seed_run_id="seed:fixture", prepared=prepared, operation_id="operation:context:alpha",
        actor_id="user:example", decided_at=decided,
    )
    creation_b = prepare_research_context_creation(
        project_id=API_PROJECT, study_definition_id="study:beta",
        seed_run_id="seed:fixture", prepared=prepared, operation_id="operation:context:beta",
        actor_id="user:example", decided_at=decided,
    )
    from fastapi.encoders import jsonable_encoder
    base = f"/api/projects/{API_PROJECT}/protocol-workflow"
    with client_for(db, designs=designs) as c:
        a = c.post(base + "/study-definitions", json=jsonable_encoder(creation_a))
        b = c.post(base + "/study-definitions", json=jsonable_encoder(creation_b))
        assert a.status_code == 200, a.text
        assert b.status_code == 200, b.text
        listing = c.get(base + "/design/regimen/study-context").json()["studies"]
        study_ids = [item["study_definition_id"] for item in listing]
        intent_a = {
            "study_definition_id": "study:alpha",
            "operation_id": "operation:regimen:alpha",
            "expected_revision": 1,
            "snapshot_sha256": a.json()["revision_sha256"],
            "actor_id": "user:example",
            "decided_at": "2026-09-13T07:00:00+00:00",
            "reason": "采用完整给药方案",
        }
        legacy_response = c.post(base + "/study-definitions", json=_create_body(study_definition_id="study:legacy"))
        assert legacy_response.status_code == 200, legacy_response.text
        legacy = legacy_response.json()
        before_wrong = _dump(db)
        wrong = c.post(
            base + "/design/regimen/" + run + "/adopt",
            json={**intent_a, "study_definition_id": "study:legacy", "snapshot_sha256": legacy["revision_sha256"]},
        )
        after_wrong = _dump(db)
        adopted_a = c.post(base + "/design/regimen/" + run + "/adopt", json=intent_a)
        intent_b = {
            "study_definition_id": "study:beta",
            "operation_id": "operation:regimen:beta",
            "expected_revision": 1,
            "snapshot_sha256": b.json()["revision_sha256"],
            "actor_id": "user:example",
            "decided_at": "2026-09-13T07:00:00+00:00",
            "reason": "采用完整给药方案",
        }
        before_b = _dump(db)
        adopted_b = c.post(base + "/design/regimen/" + run + "/adopt", json=intent_b)
        producer_a = adopted_a.json()["definition"]["facts"].get("research.regimen_producer", {})
        producer_b = adopted_b.json()["definition"]["facts"].get("research.regimen_producer", {}) if adopted_b.status_code == 200 else {}
        record(
            "wrong_study_and_cross_study_same_context",
            listed_study_ids=study_ids,
            both_studies_share_input_context=a.json()["definition"]["facts"]["research.input_context"]
            == b.json()["definition"]["facts"]["research.input_context"] == context,
            wrong_legacy_status=wrong.status_code,
            wrong_dump_unchanged=before_wrong == after_wrong,
            adopt_alpha_status=adopted_a.status_code,
            adopt_beta_status=adopted_b.status_code,
            same_run_bound_to_two_studies=adopted_a.status_code == 200 and adopted_b.status_code == 200
            and producer_a.get("workflow_run_id") == producer_b.get("workflow_run_id") == run,
            run_id=run,
            beta_dump_changed=before_b != _dump(db),
            ok=wrong.status_code == 409 and before_wrong == after_wrong
            and adopted_a.status_code == 200 and adopted_b.status_code == 200,
        )


def probe_study_context_api_identity_and_legacy(tmp):
    db = tmp / "context.sqlite"
    shared.admit(db, SOURCE_PROJECT)
    opener = _FakeOpener([
        _FakeResponse(_completion_body(content='{"fields":{}}')),
        _FakeResponse(_completion_body(content='{"fields":{}}')),
    ])
    seeds = make_seeds(db, opener)
    endpoint = BASE.removesuffix("/sources")
    context = endpoint + "/design/regimen/study-context"
    expected_study = "study:v3:" + hashlib.sha256(SOURCE_PROJECT.encode()).hexdigest()[:32]
    with client_for(db, seeds=seeds) as c:
        source = upload(c, build_docx(paragraph_xml("历史资料中的剂量不能自动采用"))).json()["current"]["source"]
        seed = c.post(endpoint + "/research-intake", json={
            "user_brief": "准备新的研究方案",
            "source_artifact_ids": [source["source_artifact_id"]],
        })
        assert seed.status_code == 202, seed.text
        intent = {
            "seed_run_id": seed.json()["workflow_run_id"],
            "operation_id": "operation:context:one",
            "actor_id": "medical_manager",
            "decided_at": "2026-09-13T08:00:00+00:00",
        }
        created = c.post(context, json=intent)
        assert created.status_code == 200, created.text
        study_id = created.json()["study_definition_id"]
        facts = created.json()["definition"]["facts"]
        graph = c.get(f"{endpoint}/study-definitions/{study_id}/decision-graph").json()["records"]
        research_validity = next(r["current_validity"] for r in graph if r["decision_key"] == "decision:research-request")
        second = c.post(context, json={**intent, "operation_id": "operation:context:two"})
        before_second = _dump(db)
        replay = c.post(context, json=intent)
        recover = c.post(context + "/recover", json=intent)
        missing_recover = c.post(context + "/recover", json={**intent, "operation_id": "operation:never"})
        listing = c.get(context, params={"seed_run_id": intent["seed_run_id"]}).json()["studies"]
        record(
            "study_context_create_identity_and_genesis_validity",
            derived_study_id=study_id,
            expected_from_project_hash=expected_study,
            study_id_is_project_hash=study_id == expected_study,
            genesis_fact_paths=sorted(facts),
            has_10mg=any("10 mg" in json.dumps(v, ensure_ascii=False) for v in facts.values()),
            has_picos=any(k.startswith("picos.") for k in facts),
            genesis_research_request_validity=research_validity,
            second_operation_status=second.status_code,
            second_detail=(second.json().get("detail") or {}).get("message") if second.status_code != 200 else None,
            replay_same_operation_status=replay.status_code,
            replayed=replay.json().get("replayed") if replay.status_code == 200 else None,
            recover_status=recover.status_code,
            recover_revision=recover.json().get("revision") if recover.status_code == 200 else None,
            missing_recover_status=missing_recover.status_code,
            listing_count=len(listing),
            matches_selected=listing[0]["matches_selected_inputs"] if listing else None,
            dump_unchanged_after_rejected_second=before_second == _dump(db),
            seed_calls=opener.calls,
            ok=study_id == expected_study and set(facts) == {"research.input_context"}
            and research_validity == "unverified" and second.status_code == 409
            and missing_recover.status_code == 404,
        )


def probe_legacy_study_blocks_create_and_update_keeps_10mg(tmp):
    db = tmp / "legacy.sqlite"
    shared.admit(db, SOURCE_PROJECT)
    opener = _FakeOpener([_FakeResponse(_completion_body(content='{"fields":{}}'))])
    seeds = make_seeds(db, opener)
    endpoint = BASE.removesuffix("/sources")
    context = endpoint + "/design/regimen/study-context"
    with client_for(db, seeds=seeds) as c:
        source = upload(c, build_docx(paragraph_xml("旧研究已有默认剂量"))).json()["current"]["source"]
        seed = c.post(endpoint + "/research-intake", json={
            "user_brief": "准备覆盖旧研究",
            "source_artifact_ids": [source["source_artifact_id"]],
        })
        assert seed.status_code == 202, seed.text
        legacy = c.post(endpoint + "/study-definitions", json=_create_body(
            project_id=SOURCE_PROJECT, study_definition_id="study:legacy-10mg"))
        assert legacy.status_code == 200, legacy.text
        legacy_facts = legacy.json()["definition"]["facts"]
        listing = c.get(context, params={"seed_run_id": seed.json()["workflow_run_id"]}).json()["studies"]
        intent = {
            "seed_run_id": seed.json()["workflow_run_id"],
            "operation_id": "operation:context:after-legacy",
            "actor_id": "medical_manager",
            "decided_at": "2026-09-13T08:00:00+00:00",
        }
        before = _dump(db)
        created = c.post(context, json=intent)
        after_create = _dump(db)
        update = {
            **intent,
            "operation_id": "operation:inputs:legacy",
            "expected_revision": 1,
            "snapshot_sha256": listing[0]["revision_sha256"],
        }
        updated = c.post(context + "/" + listing[0]["study_definition_id"] + "/inputs", json=update)
        updated_facts = updated.json()["definition"]["facts"] if updated.status_code == 200 else {}
        record(
            "legacy_study_blocks_create_update_preserves_10mg",
            legacy_fact_paths=sorted(legacy_facts),
            legacy_has_10mg=legacy_facts.get("picos.intervention.dose") == "10 mg 每日一次",
            listing_ids=[item["study_definition_id"] for item in listing],
            listing_count=len(listing),
            auto_select_candidate=listing[0]["study_definition_id"] if len(listing) == 1 else None,
            matches_before_update=listing[0]["matches_selected_inputs"],
            create_status=created.status_code,
            create_dump_unchanged=before == after_create,
            update_status=updated.status_code,
            updated_fact_paths=sorted(updated_facts),
            updated_still_has_10mg=updated_facts.get("picos.intervention.dose") == "10 mg 每日一次",
            updated_has_input_context="research.input_context" in updated_facts,
            ok=created.status_code == 409 and updated.status_code == 200
            and updated_facts.get("picos.intervention.dose") == "10 mg 每日一次",
        )


def probe_needs_information_not_adopted_and_lookup_returns_current(tmp):
    db = tmp / "unresolved.sqlite"
    shared.admit(db, API_PROJECT)
    prepared, output = prepared_reference()
    unresolved = {"coverage": [], "regimen": None, "questions": ["本研究是否拟采用该参考给药安排？"]}
    opener = _FakeOpener([_FakeResponse(_completion_body(content=json.dumps(unresolved)))])
    designs = make_designs(db, opener)
    run = designs(API_PROJECT).start(prepared)
    state = designs(API_PROJECT).resume(run)
    from fastapi.encoders import jsonable_encoder
    creation = prepare_research_context_creation(
        project_id=API_PROJECT, study_definition_id=SD_ID, seed_run_id="seed:fixture",
        prepared=prepared, operation_id="operation:context:unresolved",
        actor_id="user:example", decided_at=datetime(2026, 9, 13, tzinfo=timezone.utc),
    )
    base = f"/api/projects/{API_PROJECT}/protocol-workflow"
    with client_for(db, designs=designs) as c:
        created = c.post(base + "/study-definitions", json=jsonable_encoder(creation))
        assert created.status_code == 200, created.text
        intent = {
            "study_definition_id": SD_ID,
            "operation_id": "operation:regimen:unresolved",
            "expected_revision": 1,
            "snapshot_sha256": created.json()["revision_sha256"],
            "actor_id": "user:example",
            "decided_at": "2026-09-13T07:00:00+00:00",
            "reason": "采用完整给药方案",
        }
        before = _dump(db)
        recover = c.post(base + f"/design/regimen/{run}/adopt/recover", json=intent)
        adopt = c.post(base + f"/design/regimen/{run}/adopt", json=intent)
        record(
            "needs_information_not_auto_adopted",
            run_status=state["status"],
            recover_status=recover.status_code,
            adopt_status=adopt.status_code,
            dump_unchanged=before == _dump(db),
            seed_calls=opener.calls,
            ok=state["status"] == "needs_information" and recover.status_code == 404
            and adopt.status_code == 409 and before == _dump(db),
        )


def probe_historical_lookup_returns_current_after_successor(tmp):
    db = tmp / "lookup.sqlite"
    shared.admit(db, API_PROJECT)
    prepared, output = prepared_reference()
    opener = _FakeOpener([_FakeResponse(_completion_body(content=json.dumps(output)))])
    designs = make_designs(db, opener)
    run = designs(API_PROJECT).start(prepared)
    assert designs(API_PROJECT).resume(run)["status"] == "ready_for_review"
    from fastapi.encoders import jsonable_encoder
    creation = prepare_research_context_creation(
        project_id=API_PROJECT, study_definition_id=SD_ID, seed_run_id="seed:fixture",
        prepared=prepared, operation_id="operation:context:lookup",
        actor_id="user:example", decided_at=datetime(2026, 9, 13, tzinfo=timezone.utc),
    )
    base = f"/api/projects/{API_PROJECT}/protocol-workflow"
    with client_for(db, designs=designs) as c:
        created = c.post(base + "/study-definitions", json=jsonable_encoder(creation))
        intent = {
            "study_definition_id": SD_ID,
            "operation_id": "operation:regimen:lookup",
            "expected_revision": 1,
            "snapshot_sha256": created.json()["revision_sha256"],
            "actor_id": "user:example",
            "decided_at": "2026-09-13T07:00:00+00:00",
            "reason": "采用完整给药方案",
        }
        adopted = c.post(base + f"/design/regimen/{run}/adopt", json=intent)
        assert adopted.status_code == 200, adopted.text
        graph_current = c.get(base + f"/study-definitions/{SD_ID}/decision-graph").json()["records"]
        dose_before = next(r for r in graph_current if r["decision_key"] == "decision:dose-regimen")
        changed = {**adopted.json()["definition"]["facts"]["research.input_context"], "seed_proposal_sha256": "d" * 64}
        from test_mounted_api_integration import _apply_body
        update = _apply_body(
            snapshot_sha256=adopted.json()["revision_sha256"], expected_revision=2,
            idempotency_key="operation:new-inputs", decision_record_id="decision:new-inputs",
            fact_updates={"research.input_context": changed},
        )
        update["revise_confirmed_facts"] = True
        update["decision_record"]["decision_key"] = "decision:research-request"
        advanced = c.post(base + f"/study-definitions/{SD_ID}/decisions", json=update)
        assert advanced.status_code == 200, advanced.text
        after_dump = _dump(db)
        recovered = c.post(base + f"/design/regimen/{run}/adopt/recover", json=intent)
        replay = c.post(base + f"/design/regimen/{run}/adopt", json=intent)
        graph_after = c.get(base + f"/study-definitions/{SD_ID}/decision-graph").json()["records"]
        dose_after = next(r for r in graph_after if r["decision_key"] == "decision:dose-regimen")
        research_after = next(r for r in graph_after if r["decision_key"] == "decision:research-request")
        recovered_facts = recovered.json()["definition"]["facts"] if recovered.status_code == 200 else {}
        record(
            "historical_lookup_returns_current_after_successor",
            dose_validity_before=dose_before["current_validity"],
            dose_validity_after=dose_after["current_validity"],
            research_validity_after=research_after["current_validity"],
            recover_status=recovered.status_code,
            recover_revision=recovered.json().get("revision"),
            recover_replayed=recovered.json().get("replayed"),
            recover_definition_has_changed_seed=recovered_facts.get("research.input_context", {}).get("seed_proposal_sha256") == "d" * 64,
            recover_still_has_regimen="intervention.dose_regimen" in recovered_facts,
            replay_status=replay.status_code,
            replay_revision=replay.json().get("revision"),
            replay_replayed=replay.json().get("replayed"),
            dump_unchanged=after_dump == _dump(db),
            successor_did_not_rollback=advanced.json()["revision"] == 3 and recovered.json().get("revision") == 3,
            ok=dose_before["current_validity"] == "current" and dose_after["current_validity"] == "stale"
            and recovered.status_code == 200 and recovered.json().get("revision") == 3
            and after_dump == _dump(db),
        )


def probe_design_payload_ignores_study_facts():
    prepared, _ = prepared_reference()
    payload = prepared.to_payload()
    record(
        "design_payload_has_no_study_definition",
        payload_keys=sorted(payload),
        has_source_intake="source_intake" in payload,
        has_seed="seed_proposal" in payload,
        has_study_facts=any(k.startswith("picos") or k == "facts" for k in payload),
        run_id_identity_uses_seed_only=True,
        ok="source_intake" in payload and "seed_proposal" in payload and "facts" not in payload,
    )


def probe_run_id_not_study_scoped():
    prepared, _ = prepared_reference()
    from app.protocol_workflow.agent2.coordinator import RegimenCoordinator
    class _Dummy:
        def __init__(self):
            self.project_id = API_PROJECT
            self.branch_id = "branch:main"
        def run_id(self, prepared_request):
            return RegimenCoordinator.run_id(self, prepared_request)
    dummy = _Dummy()
    run = dummy.run_id(prepared)
    payload = prepared.to_payload()
    identity = canonical_json([API_PROJECT, "branch:main", "regimen-design.request.v1", payload["seed_proposal"]])
    expected = "regimen-design:" + hashlib.sha256(identity.encode()).hexdigest()
    record(
        "run_id_ignores_study_and_full_source_intake_body",
        run_id=run,
        equals_seed_proposal_hash=run == expected,
        identity_includes_study_id=False,
        identity_includes_source_intake_body=False,
        ok=run == expected,
    )


def probe_intake_bypass_condition():
    src = Path("frontend/src/features/medical-writing/protocol-workbench/ProtocolIntakeWorkspace.jsx").read_text()
    app = Path("frontend/src/App.jsx").read_text()
    functional = Path("frontend/tests/protocol-intake-functional.jsx").read_text()
    record(
        "frontend_wiring",
        intake_bypass_when_missing_actor="studyDefinitionId || !actorId" in src,
        app_passes_medical_manager='actorId="medical_manager"' in app and "ProtocolIntakeWorkspace" in app,
        functional_default_omits_actorId="actorId={contextMode ? contextFixture.actor_id : undefined}" in functional,
        study_context_auto_selects_single_study="if(result.studies.length===1)setSelectedId" in Path(
            "frontend/src/features/medical-writing/protocol-workbench/StudyContextWorkspace.jsx"
        ).read_text(),
        ok=True,
    )


def main():
    tmp = SCRATCH / "tmp"
    tmp.mkdir(exist_ok=True)
    probe_source_identity_projection()
    probe_source_seed_mismatch_and_empty_sources()
    probe_wrong_study_and_cross_study_same_context(tmp)
    probe_study_context_api_identity_and_legacy(tmp)
    probe_legacy_study_blocks_create_and_update_keeps_10mg(tmp)
    probe_needs_information_not_adopted_and_lookup_returns_current(tmp)
    probe_historical_lookup_returns_current_after_successor(tmp)
    probe_design_payload_ignores_study_facts()
    probe_run_id_not_study_scoped()
    probe_intake_bypass_condition()
    out = SCRATCH / "probe_results.json"
    out.write_text(json.dumps(RESULTS, ensure_ascii=False, indent=2, default=str))
    failed = [item["name"] for item in RESULTS if not item.get("ok")]
    print("FAILED" if failed else "ALL_PROBES_RECORDED", failed)


if __name__ == "__main__":
    main()
