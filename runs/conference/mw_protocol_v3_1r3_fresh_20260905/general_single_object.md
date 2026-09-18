I'll start from the conference context and Codex plan, then independently verify Task1R.3's real SQLite/API tests and the two error-response fixes.Context is loaded. Next I’ll read the Task1R.3 sources of truth and inspect the actual tests and product code independently.I’ll pull Task1R.3 from the immutable plan and read the integration tests plus product persistence/API code in parallel.Tests are in view. Next I’ll inspect product persistence/API code and the prior Codex receipt, then run the assigned pytest command.I’ll read commit/rollback, HTTP error mapping, and `_translate` next, then check whether the unknown-outcome tests actually commit before they fail.The unknown-commit tests look like pre-commit injection rather than true post-commit loss. I’ll confirm that in product `__exit__`/`commit`, then run the assigned pytest command.Independent pytest run is 22 passed. I’ll confirm one remaining mapping detail, then return the conference report.# Conference Participant Output: mw_protocol_v3_1r3_fresh_20260905 - general_single_object

## Boundary Check

- Role: `general_single_object` / Grok Build `grok-4.6`. Read-only review. No source, test, or config edits. Conference report file was not written; this response is the deliverable.
- Workspace only. Initial packet plus Task 1R.3 sources, the named tests, and product `storage/sqlite.py`, `application/service.py`, `api/router.py`, `api/composition.py`, `events/unit_of_work.py`, `errors.py`. Did not read project `AGENTS.md`, home AGENTS/SOUL, other participant outputs, live workbench, or monitoring trees.
- Did not run `start_stable_backend.zsh`, unconfigured `app.main` in this process, model/OCR/translation/Word, or security-specialist work. The existing `test_real_main_*` child uses `TestClient(app.main)` under `tmp_path` runtime, which the packet allows.
- Independent pytest used the assigned `env -i` command and isolated venv. Pytest created only TMPDIR databases. No extra sibling files under `runs/conference/`.
- This is not full-repository, clinical, visual, or product acceptance.

## Independent Work Product

### Verdict (advisory)

Task 1R.3 persistence, restart, WAL backup, CAS/event/outbox rollback, GET-without-business-write, and the two public error envelopes are real and currently green on the assigned 22 tests. The **highest-impact defect is a coverage false claim**, not a demonstrated double-write in the product:

The HTTP and e2e “unknown COMMIT” tests replace `SqliteUnitOfWork.commit` and raise **before** `COMMIT`. They then **manually `rollback()` captured UoWs** and assert GET 404 + `replayed is False`. That is a known pre-commit abort dressed as unknown outcome. A genuine post-commit acknowledgement loss is only proven at the ApplicationService layer by `test_commit_acknowledgement_loss.py`. If that HTTP test were pointed at the landed-commit path, its 404/`replayed is False` assertions would be wrong.

Do not treat 22 passing tests, or Codex’s earlier 1425-count XML, as proof that unknown-outcome HTTP recovery is covered.

### Highest-impact finding

| Item | Classification |
|---|---|
| HTTP `test_unknown_commit_failure_reconciles_before_retry` and e2e `TestUnknownCommitOutcome.test_commit_failure_reconciles_before_retry` inject failure **before** `original_commit` | **Evidence** |
| Both tests then `uow.rollback()` on captured units of work | **Evidence** |
| HTTP test then requires GET 404 and retry `replayed is False` | **Evidence** |
| `test_commit_acknowledgement_loss.py` calls `original_commit(self)` then raises; recovered GET finds the object; identical create is `replayed is True`; business dump unchanged | **Evidence** |
| e2e unknown-outcome `else` branch (commit landed → exact replay) is unreachable under the current injection | **Inference** |
| Replacing `commit()` bypasses product `commit()`’s `finally: close()`; `__exit__` does not roll back when `self.commit()` itself raises on the success path | **Evidence** (product `__exit__` / `commit`) |
| Manual rollback in the HTTP/e2e tests is load-bearing test mechanics, not product cleanup proof | **Inference** |

**Why it matters.** Amendment 1R.3 requires: driver-level unknown at COMMIT; reconcile by logical key; never advertise blind re-execution. The packet itself says post-commit acknowledgement-loss must genuinely commit first, and test-only commit replacement may bypass cleanup. The current HTTP test proves only: “if `commit()` raises before SQL COMMIT, `_safe_call` returns 500/`can_retry=False`, and after an artificial rollback a retry creates once.” It does **not** prove: “if COMMIT landed and the caller saw 500, GET then identical POST is a replay and not a second genesis.”

**Product behaviour on the landed path looks correct at the service layer** (ack-loss test passed independently). `_safe_call` maps untyped `Exception` (including `sqlite3.OperationalError`) to `_unexpected_envelope()` with `can_retry=False` and “暂勿重复提交.” That envelope is right. The gap is the **HTTP integration claim**, not a shown duplicate-write bug.

**Concrete remediation (do not implement in this round):**

1. Split unknown-outcome into two tests; do not keep one test that asserts only the absent terminal.
2. **Pre-commit abort (optional, label it as such):** raise before `COMMIT`; do not treat manual `rollback()` as product proof; expect GET 404 and `replayed is False`.
3. **Post-commit ack loss over HTTP (required for the 1R.3 unknown claim):**  
   `original_commit(self)` then raise once. Expect 500 + `can_retry=False` + no sqlite/path leak; GET 200 with revision 1; identical POST 200 + `replayed is True`; `dump_business_tables` unchanged; `integrity_check == ok`. No manual rollback.
4. Delete or assert-fail the dead `else` branch in e2e `TestUnknownCommitOutcome`, or force the landed injection so that branch runs.

### Coverage that is actually real

| Requirement | What the tests actually do | Status |
|---|---|---|
| Product adapter, not PoC | `build_unit_of_work_factory` / `ApplicationService` / `mount_protocol_workflow_router`; no `pocs` imports | Met |
| CAS + event + outbox one transaction | Coordinator order is CAS → event append → outbox; one `BEGIN IMMEDIATE` connection; rollback tests leave event count/hash/outbox unchanged | Met at adapter/coordinator; CAS/event faults are coordinator-direct, outbox conflict is ApplicationService |
| Close/reopen durability | Fresh factory fingerprint + outbox rows match | Met |
| Separate-process canonical hash | Child process rebuilds fingerprint via product service; JSON equality; child asserts SQLite ≥ 3.51.3 | Met as **re-read of stored snapshot + stream head**, not an independent fold of events into a new `StudyDefinition` |
| Exact replay / same-key different payload | Same-process and post-reopen replay write nothing; conflicting reason → `P1_DECISION_CAS`, one event | Met |
| WAL-consistent backup | Pin connection so WAL size > 0; `sqlite3.Connection.backup`; bare main-file copy asserted stale at rev 2/2 events vs live rev 3/3; restore via product factory; `integrity_check`; fingerprints; two admitted projects; further apply on restore to rev 4 | Met. Amendment (backup API) correctly supersedes Plan v2 “文件复制” |
| Mounted mutation → GET | FastAPI `TestClient` on mounted router; create/apply/GET/events/decision-graph agree with adapter fingerprint | Met |
| GET no business write | Dump of 10 business tables + db family names + stream head unchanged across repeated GET/404 | Met for **business rows**. GET still uses UoW `BEGIN IMMEDIATE` + success-path `commit()` (reserved lock, not proven byte-identical WAL) |
| Real `app.main` restart | Two subprocesses, isolated runtime/db, create then read; outsider 404 | Met in this venv (fitz/xlrd present). Legacy sweeper may run; test does not claim main import is side-effect free |
| Two error-response fixes | `_unexpected_envelope`: 500, `can_retry=False`, 先刷新/暂勿重复提交. Admission `SqliteStorageError`/`sqlite3.Error`/`OSError` → 503, “本次操作未执行”, `can_retry=False` | Product code present. (1) helper + mounted HTTP (pre-commit). (2) **helper-only** monkeypatch of `is_project_admitted`, not a real unreadable DB through TestClient |
| No product models / live writes / 1R.5 security pack | Integration tests are synthetic `proj:1r3:*` + tmp DBs; no new `tests/protocol_v3/security/` | Met in this bound |
| pytest collection | `pytest.ini` `testpaths = tests` recursively collects these files | Met locally. No separate CI yaml was inspected |

### Two error-response fixes (product, current)

```136:141:services/api/app/protocol_workflow/api/router.py
def _unexpected_envelope() -> dict:
    return _envelope(
        message="当前操作的结果尚未确认。",
        can_retry=False,
        next_step="请先刷新查看已保存内容，核对本次操作结果，暂勿重复提交。",
    )
```

```212:221:services/api/app/protocol_workflow/api/composition.py
        except (SqliteStorageError, sqlite3.Error, OSError) as exc:
            raise HTTPException(
                status_code=503,
                detail={
                    "message": "暂时无法读取项目存储，本次操作未执行。",
                    "responsible_area": OWNER_PUBLIC_LABEL[ProtocolErrorOwner.APPLICATION_SERVICE],
                    "can_retry": False,
                    "next_step": "请检查项目存储是否可用，恢复后刷新页面。",
                },
            ) from exc
```

`_safe_call` sends untyped exceptions to that 500 envelope; typed `ProtocolWorkflowError` still uses `to_public_payload()`. That split is the right unknown-vs-known design.

### Secondary findings (lower than the unknown-COMMIT overclaim)

1. **503 is not mounted.** `test_storage_unavailable_before_operation_has_actionable_response` patches `composition.is_project_admitted`. A missing file is 404 (`is_project_admitted` returns False), not 503. 503 is for present-but-unusable storage. No TestClient case with a real unopenable path.
2. **“Event replay rebuilds canonical hash” is snapshot re-read plus ledger rebuild.** `get_study_definition` hashes the stored aggregate. `get_study_definition_event_summary` rebuilds the decision ledger from event payloads. There is no test that folds the stream into a new `StudyDefinition` and compares `study_revision_hash` to `aggregate_revision`. Dual-write divergence after a successful commit is untested. Atomic rollback tests make that unlikely, not proven impossible.
3. **`_LedgerRebuildError` → `P1_DECISION_CAS`, `retryable=True`.** Public copy is “推荐已被更新…请查看最新推荐后重新确认.” That is the wrong card for a corrupt ledger. `_translate` documents “Never swallow unknown errors into a wrong code” and then maps ledger rebuild failure to retryable CAS. Out of the 1R.3 happy path, but it is an error-classification hole the 1R.3 mapping table does not catch (`test_abort_without_cause` does not even assert `retryable`).
4. **Outbox logical-key conflict → `P1_DECISION_CAS` / HTTP 409 / `can_retry=True`.** Chinese next_step is re-confirm, not “重新执行”. Known conflict, not unknown. Acceptable for 1R.3 if Codex does not treat `can_retry=True` as “safe to re-POST the same body.”
5. **GET takes a write lock.** Every query opens `BEGIN IMMEDIATE` and `__exit__` commits. Not a business-row write; it is lock/contention behaviour 1R.3 does not discuss.

### Challenge to the packet / Codex receipt

- Codex XML `1r3_final_codex_regression.xml`: 1425 tests, 0 fail, timestamp 2026-09-05T18:19:22+08:00. It includes these same 22 1R.3 names. A passing count does not make the unknown-COMMIT HTTP test a landed-commit test.
- Plan v2 micro-step still says backup by file copy. The 2026-09-05 amendment and the test (backup API + bare-copy contrast) are the authority. Do not regress to `shutil.copyfile` of a live main file.
- Historical full-repo collection errors remain outside this bound. 22 green ≠ P1R-G1.

## Evidence And Assumptions

### Evidence (observed)

- Assigned pytest, exact command, isolated venv: **22 passed in 6.34s**. Collect-only: 22 node ids, same set as the XML 1R.3 subset.
- Linked engine in that venv: **SQLite 3.53.4** (≥ 3.51.3 gate).
- XML receipt: 1425/0/0/0. Not re-run. Packet said not to re-run the full repo.
- HTTP unknown test: `flaky_commit` raises without calling `original_commit`; then `for uow in created_uows: uow.rollback()`; then GET 404; retry `replayed is False`.
- E2e unknown test: same pre-commit raise + manual rollback; `if observed.definition is None` retry-create; `else` replay is dead under this injection.
- Ack-loss test: `original_commit(self)` then raise; `observed.definition is not None`; `replayed is True`; dump equal. This process’s run passed, so the commit landed.
- Product `commit()`: `execute("COMMIT")` then always close in `finally`. Product `__exit__`: on block success calls `self.commit()` with no inner try; if that raises, no rollback in the same `__exit__`.
- No `pocs` imports in `tests/protocol_v3/integration`.
- `pytest.ini`: `testpaths = tests`.

### Inference

- HTTP `_safe_call` would map a real post-commit `OperationalError` to the same 500 envelope (untyped exception). Not proven through TestClient with a landed commit.
- If HTTP used the ack-loss monkeypatch, GET would be 200 and retry `replayed is True`; the current assertions would fail. Therefore that test cannot represent the landed unknown outcome.
- Manual rollback exists because replaced `commit()` never closes the connection; without it, retry could hit busy timeout. That is test mechanics.
- Fingerprint equality across processes proves durable stored bytes, not an independent event-sourced rebuild of the aggregate.

### Assumptions

- 1R.2 mount/allowlist remains independently verified; this pass only used it as a given.
- Isolated venv at `runs/mw_protocol_v3_1r_integration_20260905/venv` is the authorized interpreter.
- Synthetic identities and `tmp_path` / `WORKBENCH_RUNTIME_DIR` under pytest tmp are enough to say “no live writes” for this suite. Default `runtime/` was not audited after the run.

### Uncertainty

- Whether Codex will accept service-layer ack-loss plus HTTP pre-commit envelope as 1R.3 “unknown COMMIT” done. That is a gate decision, not a test result.
- Whether a real `execute("COMMIT")` failure (not a monkeypatch) leaves the txn open until `close()` implied rollback; product `finally: close()` likely turns many driver failures into rollback, which is conservative if callers still reconcile.
- Full `tests/protocol_v3` and full-repo collection were not run here.

## Risks, Gaps, And Verification Needs

| Risk | Why | What would close it |
|---|---|---|
| Unknown-COMMIT HTTP coverage overclaimed | Pre-commit inject + manual rollback + 404 assertions | HTTP ack-loss test as in remediation §3 |
| 503 envelope only helper-tested | Monkeypatch, not unusable file | TestClient against a present non-DB path / unreadable file after enable |
| Snapshot vs event stream after success | Restart tests re-read both; no fold-and-compare | Reduce events to `StudyDefinition` and compare `revision_sha256` |
| Ledger corruption mapped to retryable CAS | `_LedgerRebuildError` → `P1_DECISION_CAS` retryable | Mapping test + non-retryable code; 1R.3 or 1R.4, Codex chooses |
| Starting 1R.4 on a false unknown-outcome green | 1R.4 simplifies runtime semantics on this store | Keep unknown HTTP as OPEN or add the landed test first |
| Full-repo / P1R-G1 still open | Packet and PRD | Do not record 1R.3 as whole-product PASS |

**Out of scope, left open:** 1R.5 security, models, live/monitoring, historical 4 collection errors, Word, visual/browser acceptance.

## Recommended Next Step

Codex should **not** close 1R.3 unknown-outcome HTTP coverage on the current tests. Persistence, WAL backup, replay/idempotency, GET business-row freeze, real-main subprocess read, and the two envelope locators can be recorded as independently green on 22 passing tests.

**Decision points for Codex**

1. Is HTTP post-commit acknowledgement-loss a 1R.3 gate, or is service-layer ack-loss plus the 500 envelope enough?  
   - If gate: add the landed HTTP test before 1R.4.  
   - If not: write the overclaim into the task record and keep the HTTP test labeled “pre-commit abort.”
2. Must 503 be proven on a real unusable DB through the mounted router, or is the helper locator enough for the “two minimal fixes”?
3. Is “event replay 重建 canonical hash” satisfied by stored-snapshot + ledger re-read, or is fold-vs-snapshot required?

**Bounded questions**

- Q1: For 1R.3 acceptance, must mounted POST after a **landed** commit + lost ack return 500, then GET 200, then POST `replayed=true` with unchanged dump? (yes/no)
- Q2: May 1R.4 start while that HTTP landed path is untested? (yes/no)
- Q3: Is `_LedgerRebuildError` → retryable `P1_DECISION_CAS` in 1R.3 scope or deferred to 1R.4?

**Safe provisional path if Codex does not answer this session:** treat 1R.3 storage/replay/backup/GET-no-write as functionally evidenced; keep **unknown-COMMIT HTTP** and **503-over-HTTP** as open evidence gaps; do not claim P1R-G1 or start 1R.4 on the assumption that unknown HTTP recovery is proven. No source edits from this role.
