"""Owner acceptance probes. Run only after the D worker source is frozen.

Actual mounted API and temporary SQLite; no model, network or live service.
Outputs observations, never turns intermediate worker code into acceptance.
"""
from pathlib import Path
import json
import tempfile

from pytest import MonkeyPatch
from test_template_fact_adoption import (
    _admitted_client, _seed, _template_body, _dump, _facts,
    BASE, SD_ID, SPONSOR, INTERIM_FLAG, INTERIM_ADJUSTMENT,
)
from app.protocol_workflow.application.service import ApplicationService


def run_case(case):
    with tempfile.TemporaryDirectory(prefix="mw-owner-adoption-") as folder:
        with MonkeyPatch.context() as patch:
            client, database = _admitted_client(Path(folder), patch)
            with client:
                return case(client, database, patch)


def historical_replay_without_current_template(client, database, patch):
    created = _seed(client)
    body = _template_body(
        snapshot_sha256=created["revision_sha256"],
        idempotency_key="idem:owner:replay-template",
        decision_record_id="decision:owner:replay-template",
        fact_updates={SPONSOR: "合成申办方"},
    )
    first = client.post(f"{BASE}/{SD_ID}/decisions", json=body)
    assert first.status_code == 200, first.json()
    before = _dump(database)
    calls = []

    def unavailable(self):
        calls.append("current_template_load")
        raise ValueError("synthetic current template unavailable after historical adoption")

    patch.setattr(ApplicationService, "_load_current_template", unavailable)
    replay = client.post(f"{BASE}/{SD_ID}/decisions", json=body)
    return {
        "case": "historical_replay_without_current_template",
        "status": replay.status_code,
        "replayed": replay.json().get("replayed"),
        "template_load_calls": len(calls),
        "sqlite_unchanged": _dump(database) == before,
        "expected": "exact recorded request replays without loading new template rules",
        "passed": replay.status_code == 200 and replay.json().get("replayed") is True
        and not calls and _dump(database) == before,
    }


def same_work_key_new_decision(client, database, patch):
    created = _seed(client)
    first = client.post(f"{BASE}/{SD_ID}/decisions", json=_template_body(
        snapshot_sha256=created["revision_sha256"],
        idempotency_key="idem:owner:one-work",
        decision_record_id="decision:owner:first-work",
        fact_updates={SPONSOR: "合成申办方A"},
    ))
    assert first.status_code == 200, first.json()
    before = _dump(database)
    second = client.post(f"{BASE}/{SD_ID}/decisions", json=_template_body(
        snapshot_sha256=first.json()["revision_sha256"], expected_revision=2,
        idempotency_key="idem:owner:one-work",
        decision_record_id="decision:owner:second-work",
        fact_updates={SPONSOR: "合成申办方B"},
    ))
    unchanged = _dump(database) == before
    return {
        "case": "same_work_key_new_decision",
        "status": second.status_code,
        "sqlite_unchanged": unchanged,
        "current_sponsor": _facts(client).get(SPONSOR),
        "expected": "same operation key with different decision/revision/payload rejects without a new effect",
        "passed": second.status_code == 409 and unchanged,
    }


def turn_off_with_existing_parameters(client, database, patch):
    created = _seed(client)
    first = client.post(f"{BASE}/{SD_ID}/decisions", json=_template_body(
        snapshot_sha256=created["revision_sha256"],
        idempotency_key="idem:owner:interim-on",
        decision_record_id="decision:owner:interim-on",
        fact_updates={INTERIM_FLAG: True, INTERIM_ADJUSTMENT: {"method": "synthetic_alpha_spending"}},
    ))
    assert first.status_code == 200, first.json()
    before = _dump(database)
    changed = client.post(f"{BASE}/{SD_ID}/decisions", json=_template_body(
        snapshot_sha256=first.json()["revision_sha256"], expected_revision=2,
        idempotency_key="idem:owner:interim-off",
        decision_record_id="decision:owner:interim-off",
        fact_updates={INTERIM_FLAG: False},
    ))
    facts = _facts(client)
    return {
        "case": "turn_off_with_existing_parameters",
        "status": changed.status_code,
        "sqlite_unchanged": _dump(database) == before,
        "interim_flag": facts.get(INTERIM_FLAG),
        "retained_adjustment": facts.get(INTERIM_ADJUSTMENT),
        "expected": "do not save inactive contradictory current parameters merely because their own path was unchanged",
        "passed": changed.status_code == 409 and _dump(database) == before,
        "follow_on": "Then verify an explicit supported resolution can turn interim off, preserving historical values; rejecting forever is insufficient.",
    }


if __name__ == "__main__":
    results = [run_case(case) for case in (
        historical_replay_without_current_template,
        same_work_key_new_decision,
        turn_off_with_existing_parameters,
    )]
    target = Path(__file__).with_name("owner_adoption_cases.json")
    target.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(results, ensure_ascii=False, indent=2))
