"""3R.4D template-bound fact adoption over the real mounted chain.

Every test drives the actual product composition (real current authored
template ``tp_ma_07_v2``, real product SQLite file, real HTTP boundary).
Synthetic projects only; all databases live in pytest tmp directories.  No
model call, OCR, translation, Word or live surface is touched: template-bound
adoption is deterministic registry work, and the only "adoption result
querying" is the existing read-only event projection.
"""

from __future__ import annotations

import sqlite3

from test_mounted_api_integration import (
    PROJECT,
    SD_ID,
    _admitted_client,
    _apply_body,
    _create_body,
)

BASE = f"/api/projects/{PROJECT}/protocol-workflow/study-definitions"
TEMPLATE_ID = "tp_ma_07_v2"

SPONSOR = "contact.sponsor_organization"
SPONSOR_ALIAS = "synopsis.sponsor"
INTERIM_FLAG = "statistics.sample_size.interim_applicable"
INTERIM_ADJUSTMENT = "statistics.sample_size.interim_adjustment"
INDICATION = "picos.population.indication"
DOSE = "picos.intervention.dose"
SD_UNKNOWN = "sd:1r3:api:unknown"


def _adoption(template_id: str | None = TEMPLATE_ID, retired: tuple[str, ...] = ()):
    intent: dict = {}
    if template_id is not None:
        intent["template_id"] = template_id
    if retired:
        intent["retired_fact_paths"] = list(retired)
    return intent or None


def _template_body(
    *,
    snapshot_sha256: str,
    idempotency_key: str,
    expected_revision: int = 1,
    decision_record_id: str,
    fact_updates: dict | None = None,
    retired: tuple[str, ...] = (),
    template_id: str | None = TEMPLATE_ID,
    decision_key: str = "decision:template",
    input_refs: list | None = None,
    study_definition_id: str = SD_ID,
):
    body = _apply_body(
        snapshot_sha256=snapshot_sha256,
        idempotency_key=idempotency_key,
        expected_revision=expected_revision,
        decision_record_id=decision_record_id,
        fact_updates=fact_updates if fact_updates is not None else {},
    )
    body["study_definition_id"] = study_definition_id
    body["revise_confirmed_facts"] = True
    body["decision_record"]["decision_key"] = decision_key
    body["template_adoption"] = _adoption(template_id, retired)
    if input_refs is not None:
        body["decision_input_refs"] = input_refs
    return body


def _dump(database) -> tuple:
    with sqlite3.connect(database) as connection:
        return tuple(connection.iterdump())


def _facts(client, study_definition_id: str = SD_ID) -> dict:
    detail = client.get(f"{BASE}/{study_definition_id}").json()
    return detail["definition"]["facts"]


def _seed(client, study_definition_id: str = SD_ID):
    created = client.post(BASE, json=_create_body(study_definition_id=study_definition_id))
    assert created.status_code == 200
    return created.json()


def _replay_events(database):
    import integration_shared as shared
    from app.protocol_workflow.application import study_definition_stream_id
    from app.protocol_workflow.application.reconstruction import reconstruct_study
    with shared.make_factory(database)() as uow:
        events = uow.event_stream_repository.read_events(
            PROJECT, study_definition_stream_id(SD_ID)
        )
    return events, reconstruct_study(events)


# ---------------------------------------------------------------------------
# Real adoption of the current template: existing canonical value -> new value
# ---------------------------------------------------------------------------


def test_template_adoption_revises_an_existing_canonical_value(tmp_path, monkeypatch):
    client, database = _admitted_client(tmp_path, monkeypatch)
    with client:
        created = _seed(client)
        first = client.post(f"{BASE}/{SD_ID}/decisions", json=_template_body(
            snapshot_sha256=created["revision_sha256"],
            idempotency_key="idem:tpl:sponsor:1",
            decision_record_id="decision:tpl:sponsor:1",
            fact_updates={SPONSOR: "申办方A"},
            input_refs=[{"fact_path": SPONSOR}],
        ))
        assert first.status_code == 200, first.json()
        assert first.json()["replayed"] is False
        assert _facts(client)[SPONSOR] == "申办方A"

        second = client.post(f"{BASE}/{SD_ID}/decisions", json=_template_body(
            snapshot_sha256=first.json()["revision_sha256"],
            expected_revision=2,
            idempotency_key="idem:tpl:sponsor:2",
            decision_record_id="decision:tpl:sponsor:2",
            fact_updates={SPONSOR: "申办方B"},
        ))
        assert second.status_code == 200, second.json()
        assert second.json()["revision"] == 3
        assert _facts(client)[SPONSOR] == "申办方B"

        # Same key, exact replay: no second aggregate/event/outbox effect.
        before = _dump(database)
        replay = client.post(f"{BASE}/{SD_ID}/decisions", json=_template_body(
            snapshot_sha256=created["revision_sha256"],
            idempotency_key="idem:tpl:sponsor:1",
            decision_record_id="decision:tpl:sponsor:1",
            fact_updates={SPONSOR: "申办方A"},
            input_refs=[{"fact_path": SPONSOR}],
        ))
        assert replay.status_code == 200
        assert replay.json()["replayed"] is True
        assert replay.json()["revision"] == 3
        assert replay.json()["revision_sha256"] == second.json()["revision_sha256"]
        assert _dump(database) == before


def test_template_adoption_persists_snapshot_impact_and_identity_in_one_event(tmp_path, monkeypatch):
    client, database = _admitted_client(tmp_path, monkeypatch)
    with client:
        created = _seed(client)
        adopted = client.post(f"{BASE}/{SD_ID}/decisions", json=_template_body(
            snapshot_sha256=created["revision_sha256"],
            idempotency_key="idem:tpl:interim:on",
            decision_record_id="decision:tpl:interim:on",
            fact_updates={INTERIM_FLAG: True},
        ))
        assert adopted.status_code == 200, adopted.json()

        before = _dump(database)
        record = client.get(f"{BASE}/{SD_ID}/template-adoption")
        assert record.status_code == 200
        payload = record.json()
        # Registry / catalog / rules identity is source-bound, not client-claimed.
        assert payload["template"]["template_id"] == TEMPLATE_ID
        assert payload["template"]["template_sha256"] == (
            "018d28d37b3e58ee97f41414371b78fc9251cbe0942f0b8baa875948bb143756"
        )
        assert payload["template"]["registry_binding_sha256"]
        assert payload["template"]["applicability_rules_sha256"]
        assert payload["template"]["fact_binding_count"] == 743
        assert payload["template"]["applicability_rule_count"] == 70
        # Base and result revision binding is verifiable material.
        assert payload["base_revision"] == 1
        assert payload["base_revision_sha256"] == created["revision_sha256"]
        assert payload["applied_revision"] == 2
        assert payload["applied_revision_sha256"] == adopted.json()["revision_sha256"]
        # Native fact changes are the literal typed diff.
        assert payload["changed_fact_paths"] == [INTERIM_FLAG]
        assert payload["facts_after_sha256"] != payload["facts_before_sha256"]
        # B snapshot: chapters whose conditions stay unknown are 未决, not false.
        snapshot = payload["applicability_snapshot"]
        assert snapshot["study_definition_sha256"] == adopted.json()["revision_sha256"]
        statuses = {e["semantic_node_id"]: e["status"] for e in snapshot["entries"]}
        assert len(statuses) == 111
        assert "applicable" in set(statuses.values())
        assert "conditional" in set(statuses.values())
        # C impact: candidates and confirmed reopens are separate and typed.
        plan = payload["impact_plan"]
        assert plan["template_id"] == TEMPLATE_ID
        assert plan["registry_sha256"] == payload["template"]["registry_sha256"]
        assert plan["changed_canonical_paths"] == [INTERIM_FLAG]
        assert plan["confirmed_reopen_contract_ids"] or plan["candidate_check_contract_ids"]
        assert not (
            set(plan["confirmed_reopen_contract_ids"])
            & set(plan["candidate_check_contract_ids"])
        )
        # Read-only query: no write, no second adoption, no hidden model call.
        assert _dump(database) == before
        again = client.get(f"{BASE}/{SD_ID}/template-adoption")
        assert again.status_code == 200
        assert again.json() == payload


def test_template_adoption_without_history_returns_not_found(tmp_path, monkeypatch):
    client, _ = _admitted_client(tmp_path, monkeypatch)
    with client:
        _seed(client)
        missing = client.get(f"{BASE}/{SD_ID}/template-adoption")
        assert missing.status_code == 404
        detail = missing.json()["detail"]
        assert detail["can_retry"] is False
        assert "未找到" in detail["message"]


# ---------------------------------------------------------------------------
# B input validation before adoption: native types, alias and inactive conflicts
# ---------------------------------------------------------------------------


def test_string_false_is_rejected_for_a_boolean_bound_fact(tmp_path, monkeypatch):
    client, database = _admitted_client(tmp_path, monkeypatch)
    with client:
        created = _seed(client)
        before = _dump(database)
        rejected = client.post(f"{BASE}/{SD_ID}/decisions", json=_template_body(
            snapshot_sha256=created["revision_sha256"],
            idempotency_key="idem:tpl:type:string",
            decision_record_id="decision:tpl:type:string",
            fact_updates={INTERIM_FLAG: "false"},
        ))
        assert rejected.status_code == 409
        detail = rejected.json()["detail"]
        assert detail["can_retry"] is True
        assert _dump(database) == before

        native = client.post(f"{BASE}/{SD_ID}/decisions", json=_template_body(
            snapshot_sha256=created["revision_sha256"],
            idempotency_key="idem:tpl:type:native",
            decision_record_id="decision:tpl:type:native",
            fact_updates={INTERIM_FLAG: False},
        ))
        assert native.status_code == 200, native.json()
        assert _facts(client)[INTERIM_FLAG] is False


def test_null_fact_value_is_not_a_delete(tmp_path, monkeypatch):
    client, database = _admitted_client(tmp_path, monkeypatch)
    with client:
        created = _seed(client)
        adopted = client.post(f"{BASE}/{SD_ID}/decisions", json=_template_body(
            snapshot_sha256=created["revision_sha256"],
            idempotency_key="idem:tpl:null:seed",
            decision_record_id="decision:tpl:null:seed",
            fact_updates={SPONSOR: "申办方A"},
        ))
        assert adopted.status_code == 200
        before = _dump(database)
        rejected = client.post(f"{BASE}/{SD_ID}/decisions", json=_template_body(
            snapshot_sha256=adopted.json()["revision_sha256"],
            expected_revision=2,
            idempotency_key="idem:tpl:null:del",
            decision_record_id="decision:tpl:null:del",
            fact_updates={SPONSOR: None},
        ))
        assert rejected.status_code == 409
        assert _dump(database) == before
        assert _facts(client)[SPONSOR] == "申办方A"


def test_alias_value_contradiction_needs_explicit_retirement(tmp_path, monkeypatch):
    client, database = _admitted_client(tmp_path, monkeypatch)
    with client:
        created = _seed(client)
        alias_first = client.post(f"{BASE}/{SD_ID}/decisions", json=_template_body(
            snapshot_sha256=created["revision_sha256"],
            idempotency_key="idem:tpl:alias:a",
            decision_record_id="decision:tpl:alias:a",
            fact_updates={SPONSOR_ALIAS: "申办方甲"},
        ))
        assert alias_first.status_code == 200, alias_first.json()

        # Writing the canonical owner with the SAME value keeps the confirmed
        # mapping consistent; the alias read stays the source, never a guess.
        aligned = client.post(f"{BASE}/{SD_ID}/decisions", json=_template_body(
            snapshot_sha256=alias_first.json()["revision_sha256"],
            expected_revision=2,
            idempotency_key="idem:tpl:alias:b",
            decision_record_id="decision:tpl:alias:b",
            fact_updates={SPONSOR: "申办方甲"},
        ))
        assert aligned.status_code == 200, aligned.json()

        # Now a different canonical value while the old alias survives is the
        # contradiction: it is blocked and the system never silently picks a
        # winner between the two.
        before = _dump(database)
        blocked = client.post(f"{BASE}/{SD_ID}/decisions", json=_template_body(
            snapshot_sha256=aligned.json()["revision_sha256"],
            expected_revision=3,
            idempotency_key="idem:tpl:alias:c",
            decision_record_id="decision:tpl:alias:c",
            fact_updates={SPONSOR: "申办方乙"},
        ))
        assert blocked.status_code == 409
        assert _dump(database) == before

        # Explicit retirement of the old alias unlocks the canonical revision.
        retired = client.post(f"{BASE}/{SD_ID}/decisions", json=_template_body(
            snapshot_sha256=aligned.json()["revision_sha256"],
            expected_revision=3,
            idempotency_key="idem:tpl:alias:d",
            decision_record_id="decision:tpl:alias:d",
            fact_updates={SPONSOR: "申办方乙"},
            retired=(SPONSOR_ALIAS,),
        ))
        assert retired.status_code == 200, retired.json()
        facts = _facts(client)
        assert facts[SPONSOR] == "申办方乙"
        assert SPONSOR_ALIAS not in facts

        # History keeps the retired alias: revision 3 is untouched and a fresh
        # store connection rebuilds the same current result from events only.
        with sqlite3.connect(database) as connection:
            history = connection.execute(
                "SELECT COUNT(*) FROM event_stream"
            ).fetchone()[0]
        assert history == 4  # create + alias + aligned canonical + retirement
        events, outcome = _replay_events(database)
        assert len(events) == 4
        assert not outcome.is_quarantined
        assert outcome.success.canonical_revision_sha256 == retired.json()["revision_sha256"]
        assert SPONSOR_ALIAS not in outcome.success.final_state.facts
        import integration_shared as shared
        with shared.make_factory(database)() as uow:
            previous = uow.study_definition_repository.get_at_revision(
                PROJECT, SD_ID, 3
            )
        assert previous is not None
        assert previous.facts[SPONSOR_ALIAS] == "申办方甲"
        assert previous.facts[SPONSOR] == "申办方甲"


def test_retirement_intent_is_typed_and_restricted_to_confirmed_aliases(tmp_path, monkeypatch):
    client, database = _admitted_client(tmp_path, monkeypatch)
    with client:
        created = _seed(client)
        adopted = client.post(f"{BASE}/{SD_ID}/decisions", json=_template_body(
            snapshot_sha256=created["revision_sha256"],
            idempotency_key="idem:tpl:ret:seed",
            decision_record_id="decision:tpl:ret:seed",
            fact_updates={SPONSOR_ALIAS: "申办方甲"},
        ))
        assert adopted.status_code == 200

        before = _dump(database)
        cases = (
            ((SPONSOR,), "canonical", {SPONSOR: "申办方乙"}),   # canonical owner: not an alias
            (("not.in.catalog",), "unknown", {}),               # no confirmed mapping at all
            (("synopsis.overall_duration",), "absent", {}),     # confirmed alias, but absent from facts
        )
        for bad, key, updates in cases:
            body = _template_body(
                snapshot_sha256=adopted.json()["revision_sha256"],
                expected_revision=2,
                idempotency_key=f"idem:tpl:ret:{key}",
                decision_record_id=f"decision:tpl:ret:{key}",
                fact_updates=updates,
                retired=bad,
            )
            rejected = client.post(f"{BASE}/{SD_ID}/decisions", json=body)
            assert rejected.status_code == 409, (key, rejected.json())
        assert _dump(database) == before

        # Retirement alone (no fact updates) is a legitimate explicit removal.
        retirement_only = client.post(f"{BASE}/{SD_ID}/decisions", json=_template_body(
            snapshot_sha256=adopted.json()["revision_sha256"],
            expected_revision=2,
            idempotency_key="idem:tpl:ret:only",
            decision_record_id="decision:tpl:ret:only",
            fact_updates={},
            retired=(SPONSOR_ALIAS,),
        ))
        assert retirement_only.status_code == 200, retirement_only.json()
        facts = _facts(client)
        assert SPONSOR_ALIAS not in facts
        record = client.get(f"{BASE}/{SD_ID}/template-adoption").json()
        assert record["retired_fact_paths"] == [SPONSOR_ALIAS]
        assert record["changed_fact_paths"] == [SPONSOR_ALIAS]


def test_inactive_conditional_conflict_blocks_adoption(tmp_path, monkeypatch):
    client, database = _admitted_client(tmp_path, monkeypatch)
    with client:
        created = _seed(client)
        off = client.post(f"{BASE}/{SD_ID}/decisions", json=_template_body(
            snapshot_sha256=created["revision_sha256"],
            idempotency_key="idem:tpl:cond:off",
            decision_record_id="decision:tpl:cond:off",
            fact_updates={INTERIM_FLAG: False},
        ))
        assert off.status_code == 200

        # The condition is decided 不适用: a material value for the controlled
        # path contradicts it and is blocked before adoption.
        before = _dump(database)
        blocked = client.post(f"{BASE}/{SD_ID}/decisions", json=_template_body(
            snapshot_sha256=off.json()["revision_sha256"],
            expected_revision=2,
            idempotency_key="idem:tpl:cond:conflict",
            decision_record_id="decision:tpl:cond:conflict",
            fact_updates={INTERIM_ADJUSTMENT: {"method": "alpha_spending"}},
        ))
        assert blocked.status_code == 409
        assert _dump(database) == before
        assert INTERIM_ADJUSTMENT not in _facts(client)


def test_unknown_condition_allows_partial_save_without_forced_completeness(tmp_path, monkeypatch):
    client, database = _admitted_client(tmp_path, monkeypatch)
    with client:
        # A fresh study whose interim flag is absent: the condition stays 未决.
        created = _seed(client, SD_UNKNOWN)
        partial = client.post(f"{BASE}/{SD_UNKNOWN}/decisions", json=_template_body(
            snapshot_sha256=created["revision_sha256"],
            idempotency_key="idem:tpl:unknown:partial",
            decision_record_id="decision:tpl:unknown:partial",
            fact_updates={INTERIM_ADJUSTMENT: {"method": "alpha_spending"}},
            study_definition_id=SD_UNKNOWN,
        ))
        assert partial.status_code == 200, partial.json()
        # The controlled path is saved while the condition is unresolved; the
        # snapshot records the chapter as 未决 instead of forcing a fake value.
        record = client.get(f"{BASE}/{SD_UNKNOWN}/template-adoption").json()
        snapshot = record["applicability_snapshot"]
        entries = {e["semantic_node_id"]: e for e in snapshot["entries"]}
        pending = [e for e in entries.values() if e["status"] == "conditional"]
        assert pending, "unknown conditions must stay 未决 in the snapshot"
        plan = record["impact_plan"]
        assert plan["confirmed_reopen_contract_ids"] == []
        assert INTERIM_ADJUSTMENT in record["changed_fact_paths"]


# ---------------------------------------------------------------------------
# CAS material, concurrency and legacy compatibility
# ---------------------------------------------------------------------------


def test_same_key_with_different_template_intent_is_rejected(tmp_path, monkeypatch):
    client, database = _admitted_client(tmp_path, monkeypatch)
    with client:
        created = _seed(client)
        body = _template_body(
            snapshot_sha256=created["revision_sha256"],
            idempotency_key="idem:tpl:intent",
            decision_record_id="decision:tpl:intent",
            fact_updates={SPONSOR: "申办方A"},
        )
        first = client.post(f"{BASE}/{SD_ID}/decisions", json=body)
        assert first.status_code == 200

        before = _dump(database)
        altered = dict(body)
        altered["template_adoption"] = _adoption(retired=(SPONSOR_ALIAS,))
        conflict = client.post(f"{BASE}/{SD_ID}/decisions", json=altered)
        assert conflict.status_code == 409
        assert _dump(database) == before

        # A different template identity is a different intent as well: the
        # typed adoption rejection names the mismatch and nothing is written.
        stale_template = dict(body)
        stale_template["template_adoption"] = _adoption(template_id="tp_ma_06_old")
        mismatch = client.post(f"{BASE}/{SD_ID}/decisions", json=stale_template)
        assert mismatch.status_code == 409
        assert mismatch.json()["detail"]["can_retry"] is True
        assert _dump(database) == before


def test_concurrent_template_adoptions_cas_one_wins_one_retries(tmp_path, monkeypatch):
    client, database = _admitted_client(tmp_path, monkeypatch)
    with client:
        created = _seed(client)
        left = _template_body(
            snapshot_sha256=created["revision_sha256"],
            idempotency_key="idem:tpl:race:left",
            decision_record_id="decision:tpl:race:left",
            decision_key="decision:race:left",
            fact_updates={SPONSOR: "申办方左"},
        )
        right = _template_body(
            snapshot_sha256=created["revision_sha256"],
            idempotency_key="idem:tpl:race:right",
            decision_record_id="decision:tpl:race:right",
            decision_key="decision:race:right",
            fact_updates={SPONSOR: "申办方右"},
        )
        winner = client.post(f"{BASE}/{SD_ID}/decisions", json=left)
        assert winner.status_code == 200, winner.json()
        loser = client.post(f"{BASE}/{SD_ID}/decisions", json=right)
        assert loser.status_code == 409
        detail = loser.json()["detail"]
        assert detail["can_retry"] is True
        assert "刷新" in detail["next_step"]
        assert _facts(client)[SPONSOR] == "申办方左"
        # Winner is durable and queryable; loser wrote nothing.
        record = client.get(f"{BASE}/{SD_ID}/template-adoption")
        assert record.json()["applied_revision"] == 2


def test_legacy_apply_and_replay_stay_compatible_without_template_context(tmp_path, monkeypatch):
    client, database = _admitted_client(tmp_path, monkeypatch)
    with client:
        created = _seed(client)
        legacy = _apply_body(
            snapshot_sha256=created["revision_sha256"],
            idempotency_key="idem:tpl:legacy",
            fact_updates={"picos.population.age": "成人"},
        )
        applied = client.post(f"{BASE}/{SD_ID}/decisions", json=legacy)
        assert applied.status_code == 200
        adopted = client.post(f"{BASE}/{SD_ID}/decisions", json=_template_body(
            snapshot_sha256=applied.json()["revision_sha256"],
            expected_revision=2,
            idempotency_key="idem:tpl:legacy:after",
            decision_record_id="decision:tpl:legacy:after",
            fact_updates={SPONSOR: "申办方A"},
        ))
        assert adopted.status_code == 200
        record_before = client.get(f"{BASE}/{SD_ID}/template-adoption").json()
        before = _dump(database)
        # The old legacy command replays byte-identically even after template
        # adoptions exist: historical replays never require a template load.
        replay = client.post(f"{BASE}/{SD_ID}/decisions", json=legacy)
        assert replay.status_code == 200
        assert replay.json()["replayed"] is True
        assert replay.json()["revision"] == 3
        assert _dump(database) == before
        # The legacy replay did not create or move a template adoption record.
        assert client.get(f"{BASE}/{SD_ID}/template-adoption").json() == record_before


def test_revising_a_bound_fact_makes_related_confirmation_stale_not_unrelated(tmp_path, monkeypatch):
    client, database = _admitted_client(tmp_path, monkeypatch)
    with client:
        created = _seed(client)
        dose = client.post(f"{BASE}/{SD_ID}/decisions", json=_template_body(
            snapshot_sha256=created["revision_sha256"],
            idempotency_key="idem:tpl:rel:dose",
            decision_record_id="decision:tpl:rel:dose",
            decision_key="decision:tpl:rel:dose",
            fact_updates={DOSE: "20 mg 每日一次"},
            input_refs=[{"fact_path": DOSE}],
        ))
        assert dose.status_code == 200
        unrelated = client.post(f"{BASE}/{SD_ID}/decisions", json=_template_body(
            snapshot_sha256=dose.json()["revision_sha256"],
            expected_revision=2,
            idempotency_key="idem:tpl:rel:ind",
            decision_record_id="decision:tpl:rel:ind",
            decision_key="decision:tpl:rel:ind",
            fact_updates={SPONSOR: "申办方A"},
            input_refs=[{"fact_path": INDICATION}],
        ))
        assert unrelated.status_code == 200

        rows = {
            r["decision_key"]: r
            for r in client.get(f"{BASE}/{SD_ID}/decision-graph").json()["records"]
        }
        assert rows["decision:tpl:rel:dose"]["current_validity"] == "current"

        revised = client.post(f"{BASE}/{SD_ID}/decisions", json=_template_body(
            snapshot_sha256=unrelated.json()["revision_sha256"],
            expected_revision=3,
            idempotency_key="idem:tpl:rel:rev",
            decision_record_id="decision:tpl:rel:rev",
            decision_key="decision:tpl:rel:rev",
            fact_updates={DOSE: "30 mg 每日一次"},
            input_refs=[{"fact_path": DOSE}],
        ))
        assert revised.status_code == 200

        rows = {
            r["decision_key"]: r
            for r in client.get(f"{BASE}/{SD_ID}/decision-graph").json()["records"]
        }
        assert rows["decision:tpl:rel:dose"]["current_validity"] == "stale"
        assert rows["decision:tpl:rel:ind"]["current_validity"] == "current"
        assert rows["decision:tpl:rel:rev"]["current_validity"] == "current"
        assert rows["decision:create"]["current_validity"] == "unverified"
        queue = client.get(
            f"/api/projects/{PROJECT}/protocol-workflow/workflow-runs/run:tpl:rel/decision-requests",
            params={"study_definition_id": SD_ID},
        )
        assert queue.status_code == 200
        assert {r["decision_key"] for r in queue.json()["requests"]} == {"decision:tpl:rel:dose"}


def test_adopted_events_rebuild_identically_from_a_fresh_store_connection(tmp_path, monkeypatch):
    client, database = _admitted_client(tmp_path, monkeypatch)
    with client:
        created = _seed(client)
        adopted = client.post(f"{BASE}/{SD_ID}/decisions", json=_template_body(
            snapshot_sha256=created["revision_sha256"],
            idempotency_key="idem:tpl:rebuild",
            decision_record_id="decision:tpl:rebuild",
            fact_updates={SPONSOR: "申办方A"},
            input_refs=[{"fact_path": SPONSOR}],
        ))
        assert adopted.status_code == 200

    events, outcome = _replay_events(database)
    assert len(events) == 2
    assert not outcome.is_quarantined
    assert outcome.success.canonical_revision_sha256 == adopted.json()["revision_sha256"]
    assert outcome.success.final_state.facts[SPONSOR] == "申办方A"


# ---------------------------------------------------------------------------
# Owner acceptance regressions (owner_adoption_cases 20260913)
# ---------------------------------------------------------------------------


def test_exact_replay_after_template_unavailability_replays_without_loader(
    tmp_path, monkeypatch
):
    """An identical recorded request replays ledger-first: the current
    template is never loaded, drift cannot invalidate it, a changed request
    still conflicts, and only a genuinely new adoption needs the loader."""
    from app.protocol_workflow.application.service import ApplicationService

    client, database = _admitted_client(tmp_path, monkeypatch)
    with client:
        created = _seed(client)
        body = _template_body(
            snapshot_sha256=created["revision_sha256"],
            idempotency_key="idem:tpl:drift",
            decision_record_id="decision:tpl:drift",
            fact_updates={SPONSOR: "申办方A"},
        )
        first = client.post(f"{BASE}/{SD_ID}/decisions", json=body)
        assert first.status_code == 200, first.json()

    before = _dump(database)
    calls: list[str] = []

    def unavailable(self):
        calls.append("load")
        raise ValueError("synthetic current template unavailable after adoption")

    monkeypatch.setattr(ApplicationService, "_load_current_template", unavailable)
    with client:
        replay = client.post(f"{BASE}/{SD_ID}/decisions", json=body)
        assert replay.status_code == 200, replay.json()
        assert replay.json()["replayed"] is True
        assert replay.json()["revision"] == 2
        assert calls == []
        assert _dump(database) == before

        # A changed request under the same decision still conflicts — without
        # touching the loader either.
        altered = dict(body)
        altered["template_adoption"] = _adoption(retired=(SPONSOR_ALIAS,))
        conflict = client.post(f"{BASE}/{SD_ID}/decisions", json=altered)
        assert conflict.status_code == 409
        assert calls == []
        assert _dump(database) == before

        # A genuinely new adoption is a configuration failure while the
        # current template cannot be loaded — not a request-envelope error.
        fresh = client.post(f"{BASE}/{SD_ID}/decisions", json=_template_body(
            snapshot_sha256=first.json()["revision_sha256"],
            expected_revision=2,
            idempotency_key="idem:tpl:drift:2",
            decision_record_id="decision:tpl:drift:2",
            fact_updates={SPONSOR: "申办方B"},
        ))
        assert fresh.status_code == 500
        assert calls == ["load"]
        assert _dump(database) == before


def test_same_idempotency_key_with_new_decision_is_one_operation_too_many(
    tmp_path, monkeypatch
):
    """The operation key identifies one logical operation per aggregate even
    without an outbox side effect; a new decision reusing it is rejected with
    zero effects, and a restarted process still replays the original key."""
    client, database = _admitted_client(tmp_path, monkeypatch)
    with client:
        created = _seed(client)
        first = client.post(f"{BASE}/{SD_ID}/decisions", json=_template_body(
            snapshot_sha256=created["revision_sha256"],
            idempotency_key="idem:tpl:one-op",
            decision_record_id="decision:tpl:one-op:a",
            fact_updates={SPONSOR: "申办方A"},
        ))
        assert first.status_code == 200, first.json()

        before = _dump(database)
        second = client.post(f"{BASE}/{SD_ID}/decisions", json=_template_body(
            snapshot_sha256=first.json()["revision_sha256"],
            expected_revision=2,
            idempotency_key="idem:tpl:one-op",
            decision_record_id="decision:tpl:one-op:b",
            fact_updates={SPONSOR: "申办方B"},
        ))
        assert second.status_code == 409
        assert _dump(database) == before
        assert _facts(client)[SPONSOR] == "申办方A"

    # Restart path: a fresh mount over the same store replays the original
    # request exactly, with zero new effects.
    client2, _ = _admitted_client(tmp_path, monkeypatch)
    with client2:
        before = _dump(database)
        replay = client2.post(f"{BASE}/{SD_ID}/decisions", json=_template_body(
            snapshot_sha256=created["revision_sha256"],
            idempotency_key="idem:tpl:one-op",
            decision_record_id="decision:tpl:one-op:a",
            fact_updates={SPONSOR: "申办方A"},
        ))
        assert replay.status_code == 200
        assert replay.json()["replayed"] is True
        assert replay.json()["revision"] == 2
        assert _dump(database) == before


def test_turning_condition_off_requires_retiring_now_inactive_values(
    tmp_path, monkeypatch
):
    """A condition flipped to 不适用 may not silently keep its previously
    adopted values: the contradictory result is rejected with zero effects,
    and the supported resolution retires those values explicitly in the same
    adoption while immutable history keeps them."""
    client, database = _admitted_client(tmp_path, monkeypatch)
    with client:
        created = _seed(client)
        on = client.post(f"{BASE}/{SD_ID}/decisions", json=_template_body(
            snapshot_sha256=created["revision_sha256"],
            idempotency_key="idem:tpl:off:on",
            decision_record_id="decision:tpl:off:on",
            fact_updates={INTERIM_FLAG: True, INTERIM_ADJUSTMENT: {"method": "alpha"}},
        ))
        assert on.status_code == 200, on.json()

        # Flag-only turn-off would leave an inactive contradictory parameter.
        before = _dump(database)
        blocked = client.post(f"{BASE}/{SD_ID}/decisions", json=_template_body(
            snapshot_sha256=on.json()["revision_sha256"],
            expected_revision=2,
            idempotency_key="idem:tpl:off:down",
            decision_record_id="decision:tpl:off:down",
            fact_updates={INTERIM_FLAG: False},
        ))
        assert blocked.status_code == 409
        assert _dump(database) == before
        assert _facts(client)[INTERIM_FLAG] is True
        assert _facts(client)[INTERIM_ADJUSTMENT] == {"method": "alpha"}

        # Explicit resolution: retire the now-inactive value in the same
        # adoption; true-to-false edits are never permanently blocked.
        resolved_body = _template_body(
            snapshot_sha256=on.json()["revision_sha256"],
            expected_revision=2,
            idempotency_key="idem:tpl:off:resolve",
            decision_record_id="decision:tpl:off:resolve",
            fact_updates={INTERIM_FLAG: False},
            retired=(INTERIM_ADJUSTMENT,),
        )
        resolved = client.post(f"{BASE}/{SD_ID}/decisions", json=resolved_body)
        assert resolved.status_code == 200, resolved.json()
        facts = _facts(client)
        assert facts[INTERIM_FLAG] is False
        assert INTERIM_ADJUSTMENT not in facts
        record = client.get(f"{BASE}/{SD_ID}/template-adoption").json()
        assert record["retired_fact_paths"] == [INTERIM_ADJUSTMENT]
        assert INTERIM_ADJUSTMENT in record["changed_fact_paths"]

        # Immutable history keeps the retired value; a fresh store connection
        # rebuilds the same result from events; the resolution replays exactly.
        import integration_shared as shared
        with shared.make_factory(database)() as uow:
            previous = uow.study_definition_repository.get_at_revision(
                PROJECT, SD_ID, 2
            )
        assert previous is not None
        assert previous.facts[INTERIM_FLAG] is True
        assert previous.facts[INTERIM_ADJUSTMENT] == {"method": "alpha"}

    events, outcome = _replay_events(database)
    assert len(events) == 3
    assert not outcome.is_quarantined
    assert outcome.success.canonical_revision_sha256 == resolved.json()["revision_sha256"]
    assert outcome.success.final_state.facts[INTERIM_FLAG] is False
    assert INTERIM_ADJUSTMENT not in outcome.success.final_state.facts

    with client:
        before = _dump(database)
        replay = client.post(f"{BASE}/{SD_ID}/decisions", json=resolved_body)
        assert replay.status_code == 200
        assert replay.json()["replayed"] is True
        assert _dump(database) == before


def test_retirement_needs_a_genuinely_inactive_condition(tmp_path, monkeypatch):
    """Retiring a condition-controlled fact is only resolved when the condition
    is decided 不适用 on the resulting facts: an applicable shared owner keeps
    the fact alive and unknown is not inactive."""
    client, database = _admitted_client(tmp_path, monkeypatch)
    with client:
        created = _seed(client)
        on = client.post(f"{BASE}/{SD_ID}/decisions", json=_template_body(
            snapshot_sha256=created["revision_sha256"],
            idempotency_key="idem:tpl:ret:active:on",
            decision_record_id="decision:tpl:ret:active:on",
            fact_updates={INTERIM_FLAG: True, INTERIM_ADJUSTMENT: {"method": "alpha"}},
        ))
        assert on.status_code == 200, on.json()

        # The condition is applicable: the controlled fact stays alive.
        before = _dump(database)
        active = client.post(f"{BASE}/{SD_ID}/decisions", json=_template_body(
            snapshot_sha256=on.json()["revision_sha256"],
            expected_revision=2,
            idempotency_key="idem:tpl:ret:active:off",
            decision_record_id="decision:tpl:ret:active:off",
            fact_updates={},
            retired=(INTERIM_ADJUSTMENT,),
        ))
        assert active.status_code == 409
        assert _dump(database) == before

        # Unknown is not inactive: with the flag absent the retirement is
        # rejected as well.
        created_unknown = _seed(client, SD_UNKNOWN)
        partial = client.post(f"{BASE}/{SD_UNKNOWN}/decisions", json=_template_body(
            snapshot_sha256=created_unknown["revision_sha256"],
            idempotency_key="idem:tpl:ret:unknown:on",
            decision_record_id="decision:tpl:ret:unknown:on",
            fact_updates={INTERIM_ADJUSTMENT: {"method": "alpha"}},
            study_definition_id=SD_UNKNOWN,
        ))
        assert partial.status_code == 200, partial.json()
        before_unknown = _dump(database)
        unresolved = client.post(f"{BASE}/{SD_UNKNOWN}/decisions", json=_template_body(
            snapshot_sha256=partial.json()["revision_sha256"],
            expected_revision=2,
            idempotency_key="idem:tpl:ret:unknown:off",
            decision_record_id="decision:tpl:ret:unknown:off",
            fact_updates={},
            retired=(INTERIM_ADJUSTMENT,),
            study_definition_id=SD_UNKNOWN,
        ))
        assert unresolved.status_code == 409
        assert _dump(database) == before_unknown
        # The unknown-condition save itself remains a permitted partial save.
        assert _facts(client, SD_UNKNOWN)[INTERIM_ADJUSTMENT] == {"method": "alpha"}
