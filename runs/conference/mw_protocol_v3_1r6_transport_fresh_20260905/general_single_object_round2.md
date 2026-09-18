# Conference Participant Output: mw_protocol_v3_1r6_transport_fresh_20260905 - general_single_object

## Boundary Check

- Round-2 scope obeyed: re-read only `services/api/app/protocol_workflow/runtime/adapters/zhipu_api.py` (full body, lines 122–330 verified) and `tests/protocol_v3/test_zhipu_product_transport.py` (new tests lines 651–684 verified). No product-file edits, no network/service calls, no credential-store reads, no global source reads. Design-text and SQLite-schema statements from the continuation prompt taken as Codex-attested input, not independently re-read.
- Independent verification executed offline only, scoped env (`runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python`, `-p no:cacheprovider`): **244 passed** (241 prior + 3 new), matching the reported `244passed0.61s`. Inline `python -c` re-probes of all three prior defects: all closed, zero HTTP / zero sink writes on every rejection path.
- No live probe run; Q2 remains pending by design. Runner report path untouched.

## Independent Work Product

**Verdict: the revision fully closes all three round-1 findings at the correct layer with correct tests. Prior verdict updates from "two direct-path defects" to "no known functional defects on any offline-reachable path." The single remaining acceptance blocker is unchanged: Q2 wire-shape compatibility (Codex-owned single probe, not run). The Q1 scope clarification is coherent and I endorse it with one bounded follow-up proposal.**

Revision assessment, item by item:

1. **Defect 1 (raising resolver bypassed safe probe receipt) — closed correctly.** `_complete` now wraps `credential_resolver()` in `try/except Exception → ZhipuTransportError("zhipu credential resolution failed")` (lines 149–152). Because `_complete` is shared, both probe (`_run_probe_once` catches `ZhipuTransportError` → `ok=False` receipt) and dispatch (raises typed → harness `dispatch_exception`, `dispatched=True`, no retry) are fixed by one edit. Verified live: raising-resolver `probe()` returns `False`, exactly one receipt, `error == "zhipu credential resolution failed"`, zero HTTP, zero sink writes. New test `test_raising_resolver_produces_failed_probe_receipt` pins exactly this, including `opener.calls == 0`.
2. **Defect 2 (schema-ref validated after HTTP+sink) — closed correctly.** `_dispatch` now checks `output_schema_ref` non-blank first (lines 263–265), then effort, then compose, then HTTP/sink. Verified: missing ref → `ZhipuTransportError`, zero HTTP, zero sink writes. New test `test_missing_output_schema_rejected_before_http_and_sink` pins it. Ordering now satisfies: every pre-transport-validatable condition precedes every side effect.
3. **`KeyError` on malformed direct-path artifacts — closed correctly.** `_compose_messages` (lines 248–260) now rejects non-dict artifacts and blank `ref`/`sha256` with `ZhipuTransportError("dispatch carries a malformed input artifact")` before HTTP. Verified: `[{'ref':'x'}]` → typed error, zero HTTP/sink. New test `test_malformed_artifact_rejected_typed_before_http` pins it. Blank-string resolver path unchanged and still typed (`returned no usable credential` — re-verified).
4. **Generic-vs-precise error-code trade-off — accept the choice, propose a bounded improvement.** Collapsing all resolver exceptions to generic `"zhipu credential resolution failed"` in transport receipts is the right default: arbitrary injected callables can raise arbitrary strings, and receipts/probe-state are durable-adjacent. The precise `OmpCredentialError` code remains available by calling the resolver directly. **Correction to my round-1 framing:** I presented "no safe receipt" as purely an observability gap; the fix's generic string leaves a residual triage gap worth naming — `unavailable` (fix config) vs `temporarily_blocked` (wait for expiry) vs `command_binding_unsupported` (rewire binding) need different operator responses, and neither `probe_state` nor the harness `probe_failed` result now distinguishes them. **Proposal (low priority, transport-owned):** allowlist-map the resolver module's own three stable codes through as a suffix (e.g. `"zhipu credential resolution failed: omp_credentials_temporarily_blocked"`), collapsing any unrecognized exception to the bare generic string. This is safe precisely because `omp_credentials` emits only stable codes by construction (verified round-1: `from None`, no content); the generic fallback still guards arbitrary injected resolvers. Not a blocker — direct-resolver diagnostics cover triage today.
5. **Q1 clarified scope — endorsed.** "Same stored provider binding/normal order, deliberately no blocked attempt / static substitution / rotation; bounded configuration failure, not exact parity with `peekApiKey`/`selectCredentialByType`/`getApiKey`" is self-consistent and matches the pinned test (`all-blocked → temporarily_blocked`, static row ignored). **Correction to my round-1 A2:** I framed fall-through-vs-block as an open parity question; the clarification retires it — parity was never claimed beyond binding source and normal order. Residual naming note (docs/runbook, not code): `temporarily_blocked` should tell operators "wait for block expiry, do not substitute" — the one behavior a reader importing full-omp mental models will get wrong.
6. **Round-1 self-corrections:** (a) I previously wrote the harness would convert the raising-resolver probe failure to `probe_failed` and called it sufficient — it was necessary but not sufficient, since `probe_state` stayed empty on every call path including direct-adapter use; the fix at `_complete` covers all paths, which is strictly better than my suggested `_run_probe_once`-level catch. (b) My round-1 "verify harness path" hedge is now moot: `probe()` returns `False` (no exception), so harness `ensure_probed` → `probe_failed` deterministically with a receipt recorded. (c) Untouched and still true: payload-key agreement, profile distinguishability, credential hygiene, no-retry discipline, 600 s deliberate timeout.

## Evidence And Assumptions

Evidence (this round, executed):
- `zhipu_api.py:147-194` — resolver-exception boundary inside `_complete`, shared by probe + dispatch; HTTP-error suppression and status/JSON strictness byte-unchanged.
- `zhipu_api.py:248-291` — typed artifact validation; schema-ref → effort → compose → HTTP → validate → sink ordering.
- `zhipu_api.py:293-321` — probe path unchanged except now catching the typed resolver failure via `_complete`.
- `test_zhipu_product_transport.py:651-684` — three new tests, each asserting zero side effects (`opener.calls == 0`, `sink.stored == []`) plus exact receipt error string.
- Runs: five-file suite `244 passed in 0.60s`; inline re-probe output: `probe: False | receipts: 1 | err: 'zhipu credential resolution failed' | http: 0 | sink: 0`; `schema: ZhipuTransportError | http: 0 | sink: 0`; `artifact: dispatch carries a malformed input artifact | http: 0 | sink: 0`; `blank: zhipu credential resolver returned no usable credential`.
- Not re-read this round (round-1 evidence stands): `direct_api.py`, `harness.py`, `omp_credentials.py`, `product_profiles.py`, registries, JSON profiles, other four test files.

Assumptions (updated):
- A1 (schema compat): **retired as a code risk** — Codex reports read-only verification of the actual SQLite schema, availability true, no key output. Residual: only availability was probed, not end-to-end key handling; that is what the single probe covers.
- A2 (selection parity): **superseded by clarified scope** — binding source + normal order only; no fall-through/rotation parity claimed.
- A3 (wire shape): **unchanged, sole acceptance blocker** — `reasoning_effort` top-level field, exactly-one-choice, `finish_reason == "stop"`, exact model-echo equality all asserted by fakes only.
- A4 (new): design-text Q1 clarification accurately landed in the task design doc — taken on Codex attestation, not re-read (outside round-2 read set).

## Risks, Gaps, And Verification Needs

1. **Q2 wire shape (only blocker, unchanged).** If the coding-plan endpoint nests effort, uses another `finish_reason` vocabulary, or echoes a versioned model string, the first probe fails typed — by design, zero blast radius (pending marker, `ping`-only, no retry). Need: Codex probe records requested/effective identity tuple verbatim; any amendment stays inside `_completion_body`/`_validated_completion`.
2. **Triage granularity (proposal, not blocker).** Allowlist-map the three stable `OmpCredentialError` codes into the receipt error suffix; collapse unknowns to generic. Preserves the injection-safety property Codex required while restoring blocked-vs-unavailable区分 for operators.
3. **Residual nits (acknowledge, do not action):** non-string `snippet` values render via f-string rather than raising (harness guarantees strings — unreachable, fine); empty `input_artifacts` still sends empty user content and relies on provider 400 → typed (minimal-payload philosophy, fine); 600 s probe timeout retained by design.
4. **Test-suite note:** 244-passed independently reproduced; the three new tests are behavior-pinning (side-effect counters + typed errors), not tautologies — they fail on the pre-fix code by construction (round-1 inline probes are the failing demonstrations).

## Recommended Next Step

1. **Optional micro-follow-up (transport + its test file only):** implement the A-code allowlist error suffix with a fourth focused test (blocked-code resolver → receipt error contains `omp_credentials_temporarily_blocked`; arbitrary `RuntimeError("SECRET-x")` resolver → bare generic string with `SECRET-x` absent). Ten minutes, zero contract change.
2. **Then Codex-owned single minimal probe** (`ping`-only, pending marker before, safe receipt after, no retry) — closes Q2/A3 and with it 1R.6 acceptance.
3. **Then** maintained regression, advance 2R.1. No further review rounds needed from this role absent a probe-driven shape amendment.

**Bounded questions for Codex:**
- **Q2 (still open, probe-time):** accepted top-level `reasoning_effort`? exactly-one `stop` choice? verbatim `glm-5.3-flash` echo? Report the observed triple verbatim on any deviation.
- **Q-follow (only if proposal accepted):** is the allowlist-suffix scheme (`generic: <stable-code>`, unknown → bare generic) an acceptable refinement of "no arbitrary injected strings," or is the bare-generic receipt the final decision? Either answer closes the item; provisional path is bare-generic as shipped.
