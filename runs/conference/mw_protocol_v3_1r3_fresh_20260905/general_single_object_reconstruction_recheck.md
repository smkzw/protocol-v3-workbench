I'll re-read the original conference context, then inspect the current tests and product mapping against the four claimed Task1R.3 changes.The claimed files exist. Next I’ll read the landed-HTTP, 503, reconstruction, and mapping code, then run the focused pytest set.# Conference Participant Output: mw_protocol_v3_1r3_fresh_20260905 - general_single_object

## Boundary Check

- Same-session targeted recheck, role `general_single_object` / Grok Build `grok-4.6`. Read-only. No source, test, or config edits. This response is the report; `runs/conference/mw_protocol_v3_1r3_fresh_20260905/general_single_object_reconstruction_recheck.md` was not written with tools.
- Re-read `context/mw_protocol_v3_1r3_fresh_20260905_conference_context.md`. Inspected current tests/product named in the four claims. Did not read other participant outputs, live/monitoring trees, or home AGENTS/SOUL.
- Did not run `start_stable_backend.zsh`, models, OCR, translation, Word, security-specialist work, cleanup, or archives.
- Pytest used the assigned isolated venv/`env -i` command plus `tests/protocol_v3/test_study_event_reconstruction.py`. Only TMPDIR databases were created.
- Full-repository collection debt remains outside this verdict. Not clinical/visual/product acceptance.

## Independent Work Product

### Recheck verdict (advisory)

The four previous findings are addressed in current source. Independent run: **29 passed in 6.27s** (29 collected). Codex may treat the prior unknown-COMMIT HTTP overclaim, precommit mislabel, reconstruction gap, and retryable ledger mapping as **closed on this focused suite**.

Do not treat 29 green as P1R-G1 or whole-product PASS.

### Claim 1 — landed HTTP ack-loss and real non-DB 503

**Addressed.**

`test_landed_commit_lost_acknowledgement_over_http` calls `original_commit(self)` then raises once. Asserts POST 500, `can_retry is False`, GET 200 revision 1, identical POST `replayed is True`, `dump_business_tables` unchanged, `integrity_check == ok`. No manual UoW rollback. Monkeypatch lets later commits succeed (`lost` gate). This is the landed path the first pass required.

`test_present_unusable_database_returns_503_over_http` writes non-SQLite bytes to the configured DB path, mounts the product router, POSTs without admit. Asserts 503, public envelope keys, `can_retry is False`, “未执行”, and **main file bytes unchanged**. Admission `is_project_admitted` read-only open of a present foreign file raises `SqliteStorageConfigurationError`; composition maps that to 503 before mutation. Not a helper monkeypatch.

Service-layer `test_commit_acknowledgement_loss.py` remains as the non-HTTP twin.

### Claim 2 — precommit tests renamed; absence asserted; cleanup not product proof

**Addressed.**

- HTTP: `test_injected_precommit_abort_reconciles_before_retry`. Comment states injection replaces `commit()`, so captured `uow.rollback()` is fixture cleanup, not product cleanup. Then GET 404 and retry `replayed is False`.
- E2E: class `TestInjectedPrecommitAbort` / `test_precommit_abort_reconciles_before_retry`. Dead `else` (commit landed) is gone. Explicit `assert observed.definition is None` with a comment that the landed branch lives in ack-loss tests.

Residual (not a product defect): the HTTP precommit block still narrates “unknown outcome” in an older comment. Naming of the test is correct; Codex can ignore the stale sentence.

### Claim 3 — event reconstruction without snapshot-table reads

**Addressed as a 1R.3 verifier for new streams. Sufficient for the previous gap. Not a GET replacement.**

Current design:

- `application/reconstruction.py` folds with existing `EventReplayEngine` + `StudyDefinitionReducer.apply_decision`. Reducer protocol matches `ReplayReducer` (`initial_state` / `apply(current, payload, event)` / `canonical_revision_hash`).
- Event types `study_definition.created` / `study_definition.decision_applied` match service constants. Schema `mw_protocol_v3_event_v1` with noop upcaster matches `_EVENT_SCHEMA_VERSION`.
- `service.py` adds `reconstruction_schema_version=study_genesis_v1` and `genesis_definition` **only on new create payloads**, after `_effect_payload`, before outbox hash. Apply payloads are unchanged (still carry `fact_updates` for the fold).
- Tests read the event stream through the product repository, then `reconstruct_study(events)` — no `aggregate_revision` read in the reconstructor.
- After create+fact update: `not quarantined`, `canonical_revision_sha256 == changed.revision_sha256`, `final_state == changed.definition`. Reducer also checks fold hash vs `payload["result_revision_sha256"]`.
- Missing version/genesis and future version: quarantined, detail contains `genesis baseline`, `partial_state is None`, DB dump unchanged. Does not invent state.

Compatibility: engine allow-list, upcaster, and domain `apply_decision` line up with how fresh applies are produced. Independent pytest equality is the compatibility proof.

Limitation Codex should record, not expand: `reconstruct_study` is **not** called from `get_study_definition` / GET. Runtime reads remain snapshot-table. Genesis is the immutable definition dumped **into the create event**, not a re-derive from seed fields alone, and not a read of `aggregate_revision`. That meets “fold events without snapshot-table reads.” Old streams without genesis fail closed. Do not claim the query path is event-sourced. Do not add a GET rewrite in this task.

### Claim 4 — `_LedgerRebuildError` mapping

**Addressed.**

```887:897:services/api/app/protocol_workflow/application/service.py
    if isinstance(exc, _LedgerRebuildError):
        ctx["event_id"] = exc.event_id
        return ProtocolWorkflowError(
            code=ProtocolErrorCode.P1_CHECKPOINT_EVENT_MISMATCH,
            object_id=object_id,
            owner=ProtocolErrorOwner.APPLICATION_SERVICE,
            retryable=False,
            attempt=1,
            audit_detail=exc.detail,
            audit_context=ctx,
        )
```

`test_corrupt_decision_ledger_requires_recovery_not_reconfirmation` asserts that code, `retryable is False`, and public `can_retry is False`. Catalog text for that code is restore work progress, not “推荐已被更新.” `_status_for` would emit HTTP 500, not 409. Helper unknown/503 locators remain.

### Independent test result

Command (assigned env + reconstruction file):

`.../venv/bin/python -m pytest tests/protocol_v3/integration tests/protocol_v3/test_unknown_operation_response.py tests/protocol_v3/test_commit_acknowledgement_loss.py tests/protocol_v3/test_study_event_reconstruction.py -q -p no:cacheprovider`

**29 passed in 6.27s.** Collect-only: 29 node ids, including landed HTTP, non-DB 503, precommit HTTP/e2e, ledger mapping, four reconstruction nodes.

No product models, no `start_stable_backend`, no live writes in this pass.

## Evidence And Assumptions

### Evidence

- Landed HTTP: `original_commit` then raise; GET 200; duplicate POST `replayed is True`; dump equal.
- 503 HTTP: non-DB file bytes identical after POST 503.
- Precommit HTTP/e2e: named precommit; GET/query absence asserted; rollback commented as fixture cleanup.
- Create payload only: genesis fields written in `create_study_definition`; apply path has no `genesis_definition` assignment.
- Reconstruction uses `EventReplayEngine.replay_stream` and `StudyDefinitionReducer.apply_decision`; tests passed hash and object equality after a fact update.
- Unsupported genesis parametrize `[None, study_genesis_future]` passed without DB mutation.
- `_LedgerRebuildError` → `P1_CHECKPOINT_EVENT_MISMATCH`, `retryable=False`; unit test passed.
- 29/29 green on the focused command.

### Inference

- Landed HTTP 500 body is `_unexpected_envelope()` (no sqlite tokens). The landed test does not assert envelope keys or leak tokens; the precommit sibling does. Product path is the same wrapper.
- 503 next_step still contains “存储” in composition; the mounted test does not assert that substring. Helper test does.
- GET/events still rebuild the decision ledger and hash the stored aggregate; reconstruction is an offline verifier.

### Assumptions

- Isolated venv SQLite remains ≥ 3.51.3 (previously 3.53.4; not re-probed this pass).
- Historical XML 1425-count receipt is stale relative to these new tests and was not re-run.

### Uncertainty

- Whether a read-only open of garbage bytes can leave empty `-wal`/`-shm` sidecars. Main file bytes were proven unchanged. Not observed as a write of business content.
- Full `tests/protocol_v3` and full-repo collection not run.

## Risks, Gaps, And Verification Needs

Concrete remaining items only. No new platforms.

| Item | Class | Codex action |
|---|---|---|
| Full-repo collection errors / P1R-G1 | Outside this bound, still open | Keep 1R.3 focused green separate from P1R-G1 |
| `reconstruct_study` not on GET | Scope limit, not a failed test | Record: 1R.3 reconstruction obligation is a verifier for **new** streams. Do not advertise snapshot GET as event-sourced. Do not add a GET rewrite here |
| Landed HTTP omits leak/envelope-key asserts | Test tightness, product uses `_unexpected_envelope` | Optional one-line assert; not a blocker |
| HTTP GET `/events` with a corrupt ledger | Mapping proven at `_translate`; not mounted | Do not add unless Codex wants HTTP parity; mapping defect is already fixed |
| Stale “unknown outcome” sentence in precommit HTTP comments | Comment drift | Ignore or tidy later; not functional |

No remaining defect that falsifies the four remediations on this suite.

## Recommended Next Step

Codex should **accept the four remediations on the focused 29-pass evidence** and keep historical full-repo debt open.

- Close prior findings: landed HTTP ack-loss, real non-DB 503, precommit labeling + absence assert, reconstruction verifier + non-retryable ledger mapping.
- Record reconstruction as **sufficient for 1R.3 hash-rebuild on new create events**; runtime GET remains snapshot. Do not start a GET/event-sourced rewrite in this task.
- Do not ask the user to pick extra coverage. Do not add security, models, or services.
- Do not mark P1R-G1 or whole-product acceptance from this 29-test run.

This role has no further recheck unless Codex names another concrete gap.
