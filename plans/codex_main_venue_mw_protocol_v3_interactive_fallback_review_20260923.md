# Codex Main-Venue Plan: mw_protocol_v3_interactive_fallback_review_20260923

Date: 2026-09-23
Objective: Independently review the Protocol v3 synchronous fallback chain for fact intake and authoring prefill. Verify user-selected provider/model/thinking/effort propagation, exact effective model provenance after fallback, allowed versus terminal errors, one-attempt-per-route behavior, generic-provider identity trust boundaries, configuration timing, and compatibility with existing callers. Review only; do not modify source.

## Task Decomposition

1. Trace route selection and per-route thinking/effort from settings through `main.py` into the OpenAI-compatible providers.
2. Challenge error classification, route attempt count, timeout propagation, effective identity, repeated-run reset, graceful degradation, and wrapper trust.
3. Review both fact-intake and authoring-prefill consumers, including persisted provenance and endpoint behavior.
4. Run focused tests in the review environment, identify release-blocking failures, and separate current-diff defects from stale assertions or environment gaps.
5. After Codex repairs, continue the same reviewer session for adversarial re-review and a final blocking-defect pass.

## Source Packet

- `context/mw_protocol_v3_interactive_fallback_review_20260923_conference_context.md`
- `services/api/app/ai_runtime_fallback_provider.py`
- `services/api/app/main.py`
- `services/api/app/medical_writing_fact_intake.py`
- `services/api/app/medical_writing_authoring_prefill_ai.py`
- `services/api/app/ai_gateway.py`
- `services/api/app/ai_runtime_settings.py`
- `tests/test_ai_runtime_fallback_provider.py`
- Current uncommitted diff at dispatch time

## Participant Assignments

| Role | Provider | Model | Output |
|---|---|---|---|
| `general_single_object` | `zcode` | `GLM-5.3-Flash` | `runs/conference/mw_protocol_v3_interactive_fallback_review_20260923/general_single_object.md` |

## Conference Panel Coordination

- No sub-venue chair. Codex leads the assigned panel directly.
- One fresh review plus two bounded same-session follow-ups were used. The model, provider, effort, and session remained unchanged.

## Main-Venue Review

- Codex owns source repairs, test execution, classification of stale assertions, and final acceptance.
- This conference mode has no Reasonix second-review role.
- Reviewer findings are advisory evidence and are reconciled against the current source and project Python environment.

## Timeout And Retry Tracking

- Initial review: 1018.172 s, session `sess_b561bbbe-5075-4299-86de-b03c7792183d`, completed, no route fallback.
- First same-session follow-up: 222.549 s, completed, no route fallback.
- Second same-session follow-up: 360.124 s, completed, no route fallback.
- All three outputs were incorporated. No model reroute or new review session was created.

## Codex Verification Checklist

- [x] Inspect the complete affected definitions and tests.
- [x] Repair empty-response classification, timeout propagation, graceful degradation, production trust boundary, and per-run state reset.
- [x] Confirm 401/403, invalid JSON, and model mismatch remain terminal.
- [x] Confirm allowed 408/429/500/502/503/504, transport, and empty-response failures advance at most one route.
- [x] Update three stale current-authority test assertions and the v0.11 `gap_items` fixture.
- [x] Run the nine-file focused matrix: 297 passed.
- [x] Run `tests/protocol_v3`: 2608 passed.
- [ ] Live MTPLX request: unavailable on port 11234 and outside this closing batch; no quality claim.
