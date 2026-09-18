"""3R.4 A-D 接线独立证伪脚本（fresh reviewer，不修改任何源码/fixture）。

真实挂载链 + 隔离临时SQLite；场景与既有测试不同：聚焦接线忠实性的
独立反例。运行环境与合同一致（venv 解释器、PYTHONDONTWRITEBYTECODE=1）。
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import threading
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TMP = Path(tempfile.mkdtemp(prefix="mw3r4_review_"))
DB = TMP / "review.sqlite"

os.environ["WORKBENCH_RUNTIME_DIR"] = str(TMP / "runtime")
os.environ["WORKBENCH_AI_SETTINGS_PATH"] = str(TMP / "ai.json")
os.environ["WORKBENCH_AI_ROLE_SETTINGS_PATH"] = str(TMP / "roles.json")
os.environ["WORKBENCH_ELIGIBILITY_ARTIFACT_DIR"] = str(TMP / "eligibility")
os.environ["WORKBENCH_PROTOCOL_V3_WORKFLOW_ENABLED"] = "1"
os.environ["WORKBENCH_PROTOCOL_V3_WORKFLOW_DB"] = str(DB)

PROJECT = "proj:1r3:api:admitted"
SD_ID = "sd:1r3:api:1"
BASE = f"/api/projects/{PROJECT}/protocol-workflow/study-definitions"
TEMPLATE_ID = "tp_ma_07_v2"

SPONSOR = "contact.sponsor_organization"
SPONSOR_ALIAS = "synopsis.sponsor"
INTERIM_FLAG = "statistics.sample_size.interim_applicable"
INTERIM_ADJ = "statistics.sample_size.interim_adjustment"
INTERIM_ALPHA = "statistics.sample_size.interim_alpha_adjustment"
PK_FLAG = "statistics.pk_pd_er.pk_applicable"
PD_FLAG = "statistics.pk_pd_er.pd_applicable"
ER_FLAG = "statistics.pk_pd_er.er_applicable"
PK_LINK = "statistics.pk_pd_er.endpoint_linkage"
DOSE = "picos.intervention.dose"

RESULTS = []


def record(name, ok, note=""):
    RESULTS.append({"name": name, "ok": bool(ok), "note": str(note)})
    print(("PASS " if ok else "FAIL ") + name + (" :: " + str(note) if note else ""))


# ---------------------------------------------------------------------------
# mount the real chain
# ---------------------------------------------------------------------------

import integration_shared as shared  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.protocol_workflow.api.composition import mount_protocol_workflow_router  # noqa: E402

shared.admit(DB, PROJECT)
app = FastAPI()
assert mount_protocol_workflow_router(app) is True
CLIENT = TestClient(app)


def dump() -> tuple:
    with sqlite3.connect(DB) as connection:
        return tuple(connection.iterdump())


def counts() -> dict:
    with sqlite3.connect(DB) as connection:
        return {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("aggregate_revision", "event_stream", "outbox_message")
        }


def facts(study_definition_id=SD_ID):
    detail = CLIENT.get(f"{BASE}/{study_definition_id}").json()
    return detail["definition"]["facts"]


def _decision(snapshot, expected, decision_record_id, key="decision:dose"):
    return shared.make_decision(
        decision_record_id=decision_record_id,
        decision_key=key,
        snapshot_sha256=snapshot,
        expected_state_revision=expected,
    ).model_dump(mode="json")


def create_body(study_definition_id=SD_ID, key="idem:rv:create"):
    snapshot = shared.genesis_snapshot(
        study_definition_id=study_definition_id, project_id=PROJECT
    )
    return {
        "project_id": PROJECT,
        "study_definition_id": study_definition_id,
        "idempotency_key": key,
        "expected_revision": 0,
        "actor_type": "user",
        "actor_id": shared.ACTOR_ID,
        "reason": shared.REASON,
        "decision_record": _decision(snapshot, 0, "decision:rv:create", "decision:create"),
        "normalized_seed_id": shared.SEED_ID,
        "normalized_seed_sha256": shared.SEED_SHA,
        "initial_facts": dict(shared.FACTS),
    }


def apply_body(
    snapshot, expected, key, decision_record_id, updates=None,
    study_definition_id=SD_ID, **extra
):
    body = {
        "project_id": PROJECT,
        "study_definition_id": study_definition_id,
        "idempotency_key": key,
        "expected_revision": expected,
        "actor_type": "user",
        "actor_id": shared.ACTOR_ID,
        "reason": shared.REASON,
        "decision_record": _decision(snapshot, expected, decision_record_id),
        "fact_updates": {} if updates is None else dict(updates),
        "revise_confirmed_facts": True,
        "template_adoption": {},
    }
    body.update(extra)
    return body


def seed(study_definition_id=SD_ID, key="idem:rv:create"):
    response = CLIENT.post(BASE, json=create_body(study_definition_id, key))
    assert response.status_code == 200, response.text
    return response.json()


def post(body, study_definition_id=SD_ID):
    return CLIENT.post(f"{BASE}/{study_definition_id}/decisions", json=body)


# ---------------------------------------------------------------------------
# S1 — replay / zero-write / CAS / intent rejection
# ---------------------------------------------------------------------------


def s1_replay_and_intent():
    created = seed()
    body_a = apply_body(
        created["revision_sha256"], 1, "idem:rv:s1:a", "decision:rv:s1:a",
        {SPONSOR: "申办方A"}, decision_input_refs=[{"fact_path": SPONSOR}],
    )
    first = post(body_a)
    assert first.status_code == 200, first.text

    # legacy (non-template) successor revision B
    legacy = {
        "project_id": PROJECT,
        "study_definition_id": SD_ID,
        "idempotency_key": "idem:rv:s1:b",
        "expected_revision": 2,
        "actor_type": "user",
        "actor_id": shared.ACTOR_ID,
        "reason": shared.REASON,
        "decision_record": _decision(first.json()["revision_sha256"], 2, "decision:rv:s1:b"),
        "fact_updates": {"picos.population.age": "老年"},
    }
    second = post(legacy)
    assert second.status_code == 200, second.text
    before = dump()

    # exact replay of A after the study moved on: original receipt, zero new writes,
    # successor revision preserved.
    replay = post(body_a)
    record(
        "S1.1 exact replay after successor revision: replayed & zero-write",
        replay.status_code == 200
        and replay.json()["replayed"] is True
        and replay.json()["revision"] == 3
        and replay.json()["revision_sha256"] == second.json()["revision_sha256"]
        and dump() == before,
        f"status={replay.status_code} body={replay.text[:200]}",
    )

    # same decision CAS triple but adoption intent dropped -> conflict, no writes
    dropped = dict(body_a)
    dropped.pop("template_adoption")
    dropped.pop("revise_confirmed_facts", None)
    conflict = post(dropped)
    record(
        "S1.2 same CAS triple without adoption intent rejected",
        conflict.status_code == 409 and dump() == before,
        f"status={conflict.status_code} body={conflict.text[:200]}",
    )

    # same decision triple, different retirement intent -> conflict
    altered = dict(body_a)
    altered["template_adoption"] = {"retired_fact_paths": [SPONSOR_ALIAS]}
    conflict2 = post(altered)
    record(
        "S1.3 same CAS triple with changed retirement intent rejected",
        conflict2.status_code == 409 and dump() == before,
        f"status={conflict2.status_code} body={conflict2.text[:200]}",
    )

    # same logical key, different decision -> one logical operation only
    reuse = apply_body(
        created["revision_sha256"], 1, "idem:rv:s1:a", "decision:rv:s1:a2",
        {SPONSOR: "申办方B"},
    )
    reuse_response = post(reuse)
    record(
        "S1.4 same idempotency key with new decision rejected zero-effect",
        reuse_response.status_code == 409 and dump() == before and counts()["event_stream"] == 3,
        f"status={reuse_response.status_code} counts={counts()}",
    )

    # GET zero-write (logical)
    get_before = dump()
    for path in (
        f"{BASE}/{SD_ID}",
        f"{BASE}/{SD_ID}/template-adoption",
        f"{BASE}/{SD_ID}/decision-graph",
        f"{BASE}/{SD_ID}/events",
    ):
        assert CLIENT.get(path).status_code == 200, path
    record(
        "S1.5 GET endpoints are logically zero-write",
        dump() == get_before,
        f"counts={counts()}",
    )

    # replay never consults the current template loader
    from app.protocol_workflow.application.service import ApplicationService

    calls = []
    original = ApplicationService._load_current_template

    def counting(self):
        calls.append(1)
        return original(self)

    ApplicationService._load_current_template = counting
    try:
        replay2 = post(body_a)
        fresh_calls = list(calls)
        record(
            "S1.6 replay classifies without loading the current template",
            replay2.status_code == 200
            and replay2.json()["replayed"] is True
            and fresh_calls == []
            and dump() == before,
            f"status={replay2.status_code} loader_calls={len(fresh_calls)}",
        )
    finally:
        ApplicationService._load_current_template = original


# ---------------------------------------------------------------------------
# S2 — native types / literal dotted keys / alias / null
# ---------------------------------------------------------------------------


def s2_native_types():
    from app.protocol_workflow.canonical.decision_inputs import (
        DecisionInputRef,
        bind_decision_inputs,
        current_input_validity,
    )
    from app.protocol_workflow.canonical.hashing import exact_payload_sha256
    from app.protocol_workflow.application.adoption import literal_fact_diff

    # literal dotted key vs nested member addressing are distinct universes
    facts_lr = {"a.b": {"c": 5}, "a": {"b": {"c": 999}}}
    bound = bind_decision_inputs(
        (DecisionInputRef(fact_path="a.b", members=("c",)),), facts_lr, "a" * 64
    )
    value = exact_payload_sha256({"present": True, "value": 5})
    record(
        "S2.1 literal dotted fact_path stays literal (no split)",
        bound.value_sha256[0] == value,
        f"hash={bound.value_sha256[0][:12]}",
    )

    # native false / 0 / "false" / null / missing are five distinct states
    distinct = {
        exact_payload_sha256({"present": True, "value": v})
        for v in (False, 0, "false", None)
    } | {exact_payload_sha256({"present": False, "value": None})}
    record(
        "S2.2 false/0/'false'/null/missing hash-distinct in input binding",
        len(distinct) == 5,
        f"distinct={len(distinct)}",
    )
    ref = (DecisionInputRef(fact_path="x"),)
    b1 = bind_decision_inputs(ref, {"x": False}, "a" * 64)
    cases = {
        "same False": ({"x": False}, "current"),
        "0 instead": ({"x": 0}, "stale"),
        "null instead": ({"x": None}, "stale"),
        "missing": ({}, "stale"),
        "unrelated only": ({"x": False, "y": 1}, "current"),
    }
    outcomes = {name: current_input_validity(b1, f) for name, (f, _) in cases.items()}
    record(
        "S2.3 current_input_validity: False stable, 0/null/missing stale",
        all(outcomes[name] == expected for name, (_, expected) in cases.items()),
        str(outcomes),
    )

    # literal_fact_diff type fidelity
    diff = literal_fact_diff({"x": False, "keep": 1}, {"x": 0, "keep": 1})
    record(
        "S2.4 literal_fact_diff: False->0 is a change, equal value is not",
        diff == ("x",),
        f"diff={diff}",
    )

    # adoption-level native type gates over the real template (own study id)
    sd2 = "sd:rv:s2"
    created = seed(sd2, "idem:rv:s2:create")
    # both rejections happen while the study is still at revision 1, so a 409
    # can only come from the type gate (no stale-revision interference)
    string_false = post(apply_body(
        created["revision_sha256"], 1, "idem:rv:s2:sf", "decision:rv:s2:sf",
        {INTERIM_FLAG: "false"}, study_definition_id=sd2,
    ), sd2)
    zero_bool = post(apply_body(
        created["revision_sha256"], 1, "idem:rv:s2:zb", "decision:rv:s2:zb",
        {INTERIM_FLAG: 0}, study_definition_id=sd2,
    ), sd2)
    native_false = post(apply_body(
        created["revision_sha256"], 1, "idem:rv:s2:nf", "decision:rv:s2:nf",
        {INTERIM_FLAG: False}, study_definition_id=sd2,
    ), sd2)
    record(
        "S2.5 boolean binding: 'false' and 0 rejected, native False adopted",
        string_false.status_code == 409
        and zero_bool.status_code == 409
        and native_false.status_code == 200
        and facts(sd2)[INTERIM_FLAG] is False,
        f"str={string_false.status_code} zero={zero_bool.status_code} "
        f"native={native_false.status_code}",
    )

    # null write on a brand-new path is not a silent creation of empty value
    before = dump()
    null_write = post(apply_body(
        native_false.json()["revision_sha256"], 2, "idem:rv:s2:null", "decision:rv:s2:null",
        {INTERIM_ALPHA: None}, study_definition_id=sd2,
    ), sd2)
    record(
        "S2.6 null write rejected as not-a-delete (fresh path)",
        null_write.status_code == 409 and dump() == before,
        f"status={null_write.status_code}",
    )

    # canonical alias write keeps facts under the literal alias key until retired
    alias_seed = post(apply_body(
        native_false.json()["revision_sha256"], 2, "idem:rv:s2:alias", "decision:rv:s2:alias",
        {SPONSOR_ALIAS: "申办方甲"}, study_definition_id=sd2,
    ), sd2)
    assert alias_seed.status_code == 200, alias_seed.text
    canonical_aligned = post(apply_body(
        alias_seed.json()["revision_sha256"], 3, "idem:rv:s2:align", "decision:rv:s2:align",
        {SPONSOR: "申办方甲"}, study_definition_id=sd2,
    ), sd2)
    assert canonical_aligned.status_code == 200, canonical_aligned.text
    both = facts(sd2)
    record(
        "S2.7 alias migration keeps both keys until explicit retirement",
        both.get(SPONSOR) == "申办方甲" and both.get(SPONSOR_ALIAS) == "申办方甲",
        f"sponsor={both.get(SPONSOR)!r} alias={both.get(SPONSOR_ALIAS)!r}",
    )


# ---------------------------------------------------------------------------
# S3 — true->false conflict / one-shot retirement / shared owners
# ---------------------------------------------------------------------------


def s3_conditional_conflicts():
    sd3 = "sd:rv:s3"
    created = seed(sd3, "idem:rv:s3:create")

    # seed BOTH controlled material paths under an applicable condition
    on = post(apply_body(
        created["revision_sha256"], 1, "idem:rv:s3:on", "decision:rv:s3:on",
        {INTERIM_FLAG: True, INTERIM_ADJ: {"method": "alpha"}, INTERIM_ALPHA: 0.025},
        study_definition_id=sd3,
    ), sd3)
    assert on.status_code == 200, on.text

    # flag-only flip: neither controlled path is written in this command,
    # so a block here proves the FULL resulting fact state was validated.
    before = dump()
    flip = post(apply_body(
        on.json()["revision_sha256"], 2, "idem:rv:s3:flip", "decision:rv:s3:flip",
        {INTERIM_FLAG: False}, study_definition_id=sd3,
    ), sd3)
    record(
        "S3.1 flag flip blocked by unwritten stale controlled params (full-result check)",
        flip.status_code == 409
        and dump() == before
        and facts(sd3)[INTERIM_FLAG] is True
        and facts(sd3).get(INTERIM_ADJ) == {"method": "alpha"}
        and facts(sd3).get(INTERIM_ALPHA) == 0.025,
        f"status={flip.status_code}",
    )

    # one-shot legal modification: flip + retire both, history preserved
    resolved = post(apply_body(
        on.json()["revision_sha256"], 2, "idem:rv:s3:resolve", "decision:rv:s3:resolve",
        {INTERIM_FLAG: False},
        template_adoption={"retired_fact_paths": [INTERIM_ADJ, INTERIM_ALPHA]},
        study_definition_id=sd3,
    ), sd3)
    after = facts(sd3)
    record(
        "S3.2 one-shot flip+retire succeeds and removes both params",
        resolved.status_code == 200
        and after[INTERIM_FLAG] is False
        and INTERIM_ADJ not in after
        and INTERIM_ALPHA not in after,
        f"status={resolved.status_code} facts={ {k: after.get(k) for k in (INTERIM_FLAG, INTERIM_ADJ, INTERIM_ALPHA)} }",
    )
    with shared.make_factory(DB)() as uow:
        previous = uow.study_definition_repository.get_at_revision(PROJECT, sd3, 2)
    record(
        "S3.3 history keeps retired interim parameters at the old revision",
        previous is not None
        and previous.facts[INTERIM_ADJ] == {"method": "alpha"}
        and previous.facts[INTERIM_ALPHA] == 0.025,
        f"prev_adj={previous.facts.get(INTERIM_ADJ)!r}",
    )

    # shared active owner: pk=true/pd=true keeps the shared path alive
    # (chained on the resolved revision from S3.2)
    latest_snapshot = resolved.json()["revision_sha256"]
    latest_revision = resolved.json()["revision"]
    seeded = post(apply_body(
        latest_snapshot, latest_revision, "idem:rv:s3:pk", "decision:rv:s3:pk",
        {PK_FLAG: True, PD_FLAG: True, ER_FLAG: False, PK_LINK: "主要终点与PK采样关联"},
        study_definition_id=sd3,
    ), sd3)
    if seeded.status_code != 200:
        record("S3.4 seed shared-owner facts", False, seeded.text[:300])
        return
    before = dump()
    retire = post(apply_body(
        seeded.json()["revision_sha256"], latest_revision + 1, "idem:rv:s3:ret", "decision:rv:s3:ret",
        {}, template_adoption={"retired_fact_paths": [PK_LINK]},
        study_definition_id=sd3,
    ), sd3)
    record(
        "S3.4 shared active owner blocks retirement (pk/pd applicable)",
        retire.status_code == 409 and dump() == before and PK_LINK in facts(sd3),
        f"status={retire.status_code}",
    )

    # mixed unknown owner (pd unknown) also blocks retirement
    seeded2 = post(apply_body(
        seeded.json()["revision_sha256"], latest_revision + 1, "idem:rv:s3:pk2", "decision:rv:s3:pk2",
        {PK_FLAG: True, ER_FLAG: False, PK_LINK: "主要终点与PK采样关联"},
        study_definition_id=sd3,
    ), sd3)
    assert seeded2.status_code == 200, seeded2.text
    retire2 = post(apply_body(
        seeded2.json()["revision_sha256"], latest_revision + 2, "idem:rv:s3:ret2", "decision:rv:s3:ret2",
        {}, template_adoption={"retired_fact_paths": [PK_LINK]},
        study_definition_id=sd3,
    ), sd3)
    record(
        "S3.5 unknown co-owner blocks retirement (unknown is not inactive)",
        retire2.status_code == 409,
        f"status={retire2.status_code}",
    )

    # seeding a material value while ALL owners are inactive is itself a
    # contradiction (full-result validation), so it is blocked…
    bad_seed = post(apply_body(
        seeded2.json()["revision_sha256"], latest_revision + 2, "idem:rv:s3:pk3bad", "decision:rv:s3:pk3bad",
        {PK_FLAG: False, PD_FLAG: False, ER_FLAG: False, PK_LINK: "旧关联"},
        study_definition_id=sd3,
    ), sd3)
    record(
        "S3.6a material value under an all-inactive condition is blocked",
        bad_seed.status_code == 409,
        f"status={bad_seed.status_code}",
    )

    # …the legal one-shot: seed the link under an ACTIVE owner, then flip all
    # owners off and retire the link in the SAME adoption.
    seeded_active = post(apply_body(
        seeded2.json()["revision_sha256"], latest_revision + 2, "idem:rv:s3:pk3", "decision:rv:s3:pk3",
        {PK_FLAG: True, PD_FLAG: False, ER_FLAG: False, PK_LINK: "旧关联"},
        study_definition_id=sd3,
    ), sd3)
    assert seeded_active.status_code == 200, seeded_active.text
    retire3 = post(apply_body(
        seeded_active.json()["revision_sha256"], latest_revision + 3, "idem:rv:s3:ret3", "decision:rv:s3:ret3",
        {PK_FLAG: False},
        template_adoption={"retired_fact_paths": [PK_LINK]},
        study_definition_id=sd3,
    ), sd3)
    record(
        "S3.6b one-shot all-owners-off flip+retire resolves",
        retire3.status_code == 200 and PK_LINK not in facts(sd3),
        f"status={retire3.status_code}",
    )


# ---------------------------------------------------------------------------
# S4 — fact-labeled propagation (A{x} B{x,y} C{y}) and real-template plan
# ---------------------------------------------------------------------------


def s4_propagation():
    from app.protocol_workflow.registries.dependency_graph import (
        CONFIRMATION_CANDIDATE,
        CONFIRMATION_REOPEN,
        ChapterNode,
        ConsistencyEdge,
        DependencyGraph,
        FactMembership,
        MembershipSource,
        SchedulingEdge,
        build_fact_labeled_impact_plan,
    )

    def graph():
        return DependencyGraph(
            template_id="t-syn",
            registry_sha256="r" * 64,
            nodes=tuple(
                ChapterNode(contract_id=c, node_id=c, coverage_role="leaf")
                for c in ("A", "B", "C", "D", "E")
            ),
            memberships=(
                FactMembership("A", "x", "required", MembershipSource.FACT_REQUIREMENT),
                FactMembership("B", "x", "required", MembershipSource.CONDITIONAL_TRIGGER,
                               conditional_rule_ids=("R1",)),
                FactMembership("B", "y", "required", MembershipSource.FACT_REQUIREMENT),
                FactMembership("C", "y", "required", MembershipSource.FACT_REQUIREMENT),
                FactMembership("D", "z", "required", MembershipSource.FACT_REQUIREMENT),
                FactMembership("E", "z", "required", MembershipSource.FACT_REQUIREMENT),
            ),
            scheduling_edges=(SchedulingEdge("A", "D", None, None),),
            consistency_edges=(
                ConsistencyEdge("A", "B", ("x",)),
                ConsistencyEdge("B", "C", ("y",)),
                ConsistencyEdge("D", "E", ("z",)),
            ),
            findings=(),
        )

    # change x only: A direct reopen; B candidate (its owner rule R1 undeclared
    # -> undecided); C must NOT be reopened through the B-y consistency bridge.
    plan = build_fact_labeled_impact_plan(
        graph(), facts_before={"x": 1, "y": 2}, facts_after={"x": 9, "y": 2},
        bindings=(), rules=(),
    )
    entries = {e.contract_id: e for e in plan.entries}
    record(
        "S4.1 A{x}B{x,y}C{y}: change x -> A reopen, B candidate, C untouched",
        "C" not in entries
        and entries["A"].confirmation == CONFIRMATION_REOPEN
        and entries["A"].reason.value == "direct_fact_use"
        and entries["B"].confirmation == CONFIRMATION_CANDIDATE
        and entries["B"].reason.value == "direct_fact_use",
        f"entries={ {k: e.confirmation for k, e in entries.items()} }",
    )

    # change x AND y: C reopens on its own declared y (direct), and the plan
    # keeps the changed-label provenance; the bridge never widens x onto C.
    plan2 = build_fact_labeled_impact_plan(
        graph(), facts_before={"x": 1, "y": 2}, facts_after={"x": 9, "y": 3},
        bindings=(), rules=(),
    )
    entries2 = {e.contract_id: e for e in plan2.entries}
    c_entry = entries2.get("C")
    record(
        "S4.2 change x+y -> C reopens on y only (no x label leaks to C)",
        c_entry is not None
        and c_entry.confirmation == CONFIRMATION_REOPEN
        and c_entry.via_fact_paths == ("y",)
        and "x" not in c_entry.via_fact_paths,
        f"C={c_entry}",
    )

    # equal values fabricate nothing
    plan3 = build_fact_labeled_impact_plan(
        graph(), facts_before={"x": 1, "y": 2}, facts_after={"x": 1, "y": 2},
        bindings=(), rules=(),
    )
    record(
        "S4.3 no value change -> empty plan",
        not plan3.entries and plan3.changed_canonical_paths == (),
        f"entries={len(plan3.entries)}",
    )

    # scheduling fan-out reaches D but D cannot seed E (z unchanged)
    plan4 = build_fact_labeled_impact_plan(
        graph(), facts_before={"x": 1, "y": 2, "z": 5},
        facts_after={"x": 9, "y": 2, "z": 5},
        bindings=(), rules=(),
    )
    entries4 = {e.contract_id: e for e in plan4.entries}
    record(
        "S4.4 scheduling fan-out reaches D only; E stays out (no label fabrication)",
        "D" in entries4
        and entries4["D"].reason.value == "scheduling"
        and "E" not in entries4,
        f"entries={sorted(entries4)}",
    )

    # real template: plan over a genuinely mapped canonical path (SPONSOR)
    # and over the unmapped fixture path DOSE (tracked, not silently blocked)
    from app.protocol_workflow.registries.template_runtime import (
        default_template_root,
        load_current_template,
    )
    from app.protocol_workflow.registries.dependency_graph import build_dependency_graph

    template = load_current_template(default_template_root())
    real_graph = build_dependency_graph(template.registry)

    before_facts = {SPONSOR: "申办方A"}
    after_facts = {SPONSOR: "申办方B"}
    real_plan = build_fact_labeled_impact_plan(
        real_graph,
        facts_before=before_facts,
        facts_after=after_facts,
        bindings=template.fact_catalog.bindings,
        rules=template.rules_catalog.rules,
    )
    reopen = set(real_plan.confirmed_reopen_contract_ids)
    candidate = set(real_plan.candidate_check_contract_ids)
    reasons = {e.reason.value for e in real_plan.entries}
    record(
        "S4.5 real template sponsor plan: entries typed, reopen/candidate disjoint",
        real_plan.changed_canonical_paths == (SPONSOR,)
        and len(real_plan.entries) > 0
        and not (reopen & candidate)
        and reopen | candidate == {e.contract_id for e in real_plan.entries}
        and reasons <= {"direct_fact_use", "consistency_impact", "scheduling"}
        and all(e.via_fact_paths for e in real_plan.entries),
        f"entries={len(real_plan.entries)} reopen={len(reopen)} "
        f"candidate={len(candidate)} reasons={sorted(reasons)}",
    )

    unmapped_plan = build_fact_labeled_impact_plan(
        real_graph,
        facts_before={"picos.intervention.dose": "10 mg"},
        facts_after={"picos.intervention.dose": "20 mg"},
        bindings=template.fact_catalog.bindings,
        rules=template.rules_catalog.rules,
    )
    record(
        "S4.6 unmapped fixture fact change is tracked, not fabricated as impact",
        unmapped_plan.changed_canonical_paths == ("picos.intervention.dose",)
        and unmapped_plan.unmapped_canonical_paths == ("picos.intervention.dose",)
        and not unmapped_plan.entries,
        f"unmapped={unmapped_plan.unmapped_canonical_paths} entries={len(unmapped_plan.entries)}",
    )


# ---------------------------------------------------------------------------
# S5 — transaction failure / concurrency / rebuild / hash branches
# ---------------------------------------------------------------------------


def s5_transactions_and_rebuild():
    from app.protocol_workflow.application.service import ApplicationService
    from app.protocol_workflow.application.reconstruction import reconstruct_study
    from app.protocol_workflow.application import study_definition_stream_id
    from app.protocol_workflow.errors import (
        ProtocolErrorCode,
        ProtocolWorkflowError,
    )

    # --- S5.1 post-CAS failure rolls back everything -----------------------
    db2 = TMP / "tx.sqlite"
    shared.admit(db2, PROJECT)
    factory = shared.make_factory(db2)
    service = ApplicationService(unit_of_work_factory=factory)
    created = service.create_study_definition(shared.create_command(
        project_id=PROJECT, study_definition_id=SD_ID,
        idempotency_key="idem:rv:s5:create",
    ))
    with sqlite3.connect(db2) as connection:
        baseline = connection.execute("SELECT COUNT(*) FROM aggregate_revision").fetchone()[0]
        baseline_events = connection.execute("SELECT COUNT(*) FROM event_stream").fetchone()[0]

    inner_factory = factory

    class _FailingAppend:
        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

        def append_events(self, *args, **kwargs):
            raise RuntimeError("synthetic post-CAS event append failure")

    class _WrappedUoW:
        def __init__(self, uow):
            self._uow = uow

        def __getattr__(self, name):
            attr = getattr(self._uow, name)
            if name == "event_stream_repository" and attr is not None:
                return _FailingAppend(attr)
            return attr

        def __enter__(self):
            self._uow.__enter__()
            return self

        def __exit__(self, *args):
            return self._uow.__exit__(*args)

    def wrapped_factory():
        return _WrappedUoW(inner_factory())

    broken_service = ApplicationService(unit_of_work_factory=wrapped_factory)
    command = shared.apply_command(
        project_id=PROJECT, study_definition_id=SD_ID,
        idempotency_key="idem:rv:s5:broken",
        expected_revision=1, snapshot_sha256=created.revision_sha256,
        decision_record_id="decision:rv:s5:broken",
        fact_updates={"picos.population.age": "成人"},
    )
    failed = None
    try:
        broken_service.apply_decision(command)
    except Exception as exc:  # noqa: BLE001 — reviewer probe of rollback
        failed = exc
    with sqlite3.connect(db2) as connection:
        after_agg = connection.execute("SELECT COUNT(*) FROM aggregate_revision").fetchone()[0]
        after_events = connection.execute("SELECT COUNT(*) FROM event_stream").fetchone()[0]
    record(
        "S5.1 post-CAS event-append failure leaves zero durable effect",
        failed is not None
        and after_agg == baseline
        and after_events == baseline_events,
        f"exc={type(failed).__name__} agg {baseline}->{after_agg} "
        f"events {baseline_events}->{after_events}",
    )

    # --- S5.2 real thread race on the same revision ------------------------
    db3 = TMP / "race.sqlite"
    shared.admit(db3, PROJECT)
    race_service = ApplicationService(unit_of_work_factory=shared.make_factory(db3))
    race_created = race_service.create_study_definition(shared.create_command(
        project_id=PROJECT, study_definition_id=SD_ID,
        idempotency_key="idem:rv:s5:race-create",
    ))
    barrier = threading.Barrier(2)
    outcomes = []

    def racer(tag):
        svc = ApplicationService(unit_of_work_factory=shared.make_factory(db3))
        cmd = shared.apply_command(
            project_id=PROJECT, study_definition_id=SD_ID,
            idempotency_key=f"idem:rv:s5:race:{tag.lower()}",
            expected_revision=1, snapshot_sha256=race_created.revision_sha256,
            decision_record_id=f"decision:rv:s5:race:{tag.lower()}",
            fact_updates={"picos.population.age": f"成人{tag}"},
        )
        barrier.wait()
        try:
            outcomes.append((tag, "ok", svc.apply_decision(cmd).revision))
        except ProtocolWorkflowError as exc:
            outcomes.append((tag, "error", exc.code.value))
        except Exception as exc:  # noqa: BLE001
            outcomes.append((tag, "other", type(exc).__name__))

    threads = [threading.Thread(target=racer, args=(t,)) for t in ("L", "R")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    with sqlite3.connect(db3) as connection:
        race_events = connection.execute("SELECT COUNT(*) FROM event_stream").fetchone()[0]
    oks = [o for o in outcomes if o[1] == "ok"]
    errors = [o for o in outcomes if o[1] != "ok"]
    record(
        "S5.2 concurrent CAS: exactly one winner, one conflict, +1 event",
        len(oks) == 1 and len(errors) == 1 and race_events == 2,
        f"outcomes={outcomes} events={race_events}",
    )

    # --- S5.3 rebuild + tamper detection ------------------------------------
    from app.protocol_workflow.application.commands import (
        ApplyStudyDecisionCommand,
        TemplateAdoptionIntent,
    )
    from app.protocol_workflow.canonical.decision_inputs import DecisionInputRef
    from packages.contracts.workbench_contracts.protocol_v3 import ActorType

    db4 = TMP / "rebuild.sqlite"
    shared.admit(db4, PROJECT)
    from app.protocol_workflow.registries.template_runtime import (
        default_template_root,
        load_current_template,
    )

    svc4 = ApplicationService(
        unit_of_work_factory=shared.make_factory(db4),
        current_template_loader=lambda: load_current_template(default_template_root()),
    )
    from integration_shared import make_decision

    c4 = svc4.create_study_definition(shared.create_command(
        project_id=PROJECT, study_definition_id=SD_ID,
        idempotency_key="idem:rv:s5:build-create",
    ))
    decision4 = make_decision(
        decision_record_id="decision:rv:s5:adopt",
        decision_key="decision:adopt",
        snapshot_sha256=c4.revision_sha256,
        expected_state_revision=1,
    )
    cmd4 = ApplyStudyDecisionCommand(
        project_id=PROJECT, study_definition_id=SD_ID,
        idempotency_key="idem:rv:s5:adopt", expected_revision=1,
        actor_type=ActorType.USER, actor_id=shared.ACTOR_ID, reason=shared.REASON,
        decision_record=decision4, fact_updates={SPONSOR: "申办方A"},
        revise_confirmed_facts=True,
        decision_input_refs=(DecisionInputRef(fact_path=SPONSOR),),
        template_adoption=TemplateAdoptionIntent(),
    )
    adopted4 = svc4.apply_decision(cmd4)

    def read_events(db):
        with shared.make_factory(db)() as uow:
            return uow.event_stream_repository.read_events(
                PROJECT, study_definition_stream_id(SD_ID)
            )

    events4 = read_events(db4)
    outcome4 = reconstruct_study(events4)
    record(
        "S5.3 adoption events rebuild the committed revision from scratch",
        len(events4) == 2
        and not outcome4.is_quarantined
        and outcome4.success.canonical_revision_sha256 == adopted4.revision_sha256
        and outcome4.success.final_state.facts[SPONSOR] == "申办方A",
        f"events={len(events4)} quarantined={outcome4.is_quarantined}",
    )

    # tamper (a): mutate the recorded fact_updates value, keep the hash field
    with sqlite3.connect(db4) as connection:
        row = connection.execute(
            "SELECT sequence, body_json FROM event_stream WHERE sequence=2"
        ).fetchone()
        body = json.loads(row[1])
        tampered = json.loads(row[1])
        tampered["payload"]["fact_updates"][SPONSOR] = "申办方B"
        connection.execute(
            "UPDATE event_stream SET body_json=? WHERE sequence=2",
            (json.dumps(tampered, ensure_ascii=False),),
        )
        connection.commit()
    tamper_a_failed = False
    tamper_a_code = None
    try:
        svc4.get_study_definition_event_summary(type("Q", (), {
            "project_id": PROJECT, "study_definition_id": SD_ID})())
    except ProtocolWorkflowError as exc:
        tamper_a_code = exc.code.value
        tamper_a_failed = exc.code is ProtocolErrorCode.P1_CHECKPOINT_EVENT_MISMATCH
    except Exception as exc:
        tamper_a_failed = True
        tamper_a_code = type(exc).__name__
    record(
        "S5.4 tampered fact_updates with stale intent hash fails the ledger rebuild",
        tamper_a_failed,
        f"code={tamper_a_code}",
    )

    # restore, then tamper (b): break the recorded result revision hash
    with sqlite3.connect(db4) as connection:
        connection.execute(
            "UPDATE event_stream SET body_json=? WHERE sequence=2",
            (json.dumps(body, ensure_ascii=False),),
        )
        tampered_b = json.loads(json.dumps(body, ensure_ascii=False))
        tampered_b["payload"]["result_revision_sha256"] = "f" * 64
        connection.execute(
            "UPDATE event_stream SET body_json=? WHERE sequence=2",
            (json.dumps(tampered_b, ensure_ascii=False),),
        )
        connection.commit()
    # read-back proves the tamper is visible to readers before rebuilding
    with shared.make_factory(db4)() as uow:
        check_events = uow.event_stream_repository.read_events(
            PROJECT, study_definition_stream_id(SD_ID)
        )
    tamper_visible = any(
        getattr(e, "payload", {}).get("result_revision_sha256") == "f" * 64
        for e in check_events
    )
    tamper_b_outcome = None
    try:
        tamper_b_outcome = reconstruct_study(read_events(db4))
        tamper_b_failed = bool(tamper_b_outcome.is_quarantined)
    except Exception:
        tamper_b_failed = True
    record(
        "S5.5 tampered result revision hash quarantines the rebuild",
        tamper_b_failed,
        f"tamper_visible={tamper_visible} quarantined="
        f"{getattr(tamper_b_outcome, 'is_quarantined', None)}",
    )

    # --- S5.6 hash-branch fidelity ------------------------------------------
    from app.protocol_workflow.canonical.study_definition import (
        TEMPLATE_FACT_ADOPTION_OPERATION, _fact_updates_sha256,
    )
    from app.protocol_workflow.canonical.hashing import material_sha256

    legacy_empty = _fact_updates_sha256(None)
    legacy_updates = _fact_updates_sha256({"k": 1})
    with_refs = _fact_updates_sha256(
        {"k": 1}, decision_input_refs=(DecisionInputRef(fact_path="k"),)
    )
    revise = _fact_updates_sha256({"k": 1}, revise_confirmed_facts=True)
    adoption = _fact_updates_sha256(
        {"k": 1},
        revise_confirmed_facts=True,
        decision_input_refs=(DecisionInputRef(fact_path="k"),),
        adoption_material={"request_template_id": TEMPLATE_ID, "retired_fact_paths": []},
    )
    distinct = len({legacy_empty, legacy_updates, with_refs, revise, adoption})
    # tuple vs JSON-round-tripped list must not change the adoption intent hash
    tuple_hash = _fact_updates_sha256(
        {"k": (1, 2)},
        revise_confirmed_facts=True,
        adoption_material={"request_template_id": TEMPLATE_ID, "retired_fact_paths": []},
    )
    list_hash = _fact_updates_sha256(
        {"k": [1, 2]},
        revise_confirmed_facts=True,
        adoption_material={"request_template_id": TEMPLATE_ID, "retired_fact_paths": []},
    )
    record(
        "S5.6 five CAS hash branches distinct; tuple/list serialization stable",
        distinct == 5
        and legacy_empty == material_sha256({})
        and tuple_hash == list_hash,
        f"distinct={distinct} operation={TEMPLATE_FACT_ADOPTION_OPERATION}",
    )


# ---------------------------------------------------------------------------


def main():
    scenarios = [
        ("S1", s1_replay_and_intent),
        ("S2", s2_native_types),
        ("S3", s3_conditional_conflicts),
        ("S4", s4_propagation),
        ("S5", s5_transactions_and_rebuild),
    ]
    for tag, fn in scenarios:
        try:
            fn()
        except Exception:  # noqa: BLE001
            record(f"{tag} scenario crashed", False, traceback.format_exc()[-800:])
    failed = [r for r in RESULTS if not r["ok"]]
    print(f"\n==== SUMMARY: {len(RESULTS) - len(failed)}/{len(RESULTS)} passed ====")
    out = Path(__file__).parent / "falsify_results.json"
    out.write_text(
        json.dumps({"results": RESULTS, "tmp": str(TMP)}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(f"results -> {out}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
