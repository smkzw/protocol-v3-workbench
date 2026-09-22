# Codex Conference Review: mw_protocol_v3_model_fallback_review_20260923

Date: 2026-09-23

## Verdict

PASS after owner repair and same-session follow-up. This verdict covers the bounded model-routing change only, not Protocol v3 product completion.

## Boundary Compliance

The reviewer did not modify project source or runtime artifacts. Its second-round transcript reports writing a private CodeBuddy plan file outside the declared workspace, despite the read-only assignment. That is a process-boundary deviation; the file is not a product artifact and was not used for acceptance.

## Participant Outputs Reviewed

- Initial report: `runs/conference/mw_protocol_v3_model_fallback_review_20260923/evidence_single_object.md`.
- Same-session follow-up: `runs/conference/mw_protocol_v3_model_fallback_review_20260923/evidence_single_object_round2.md`.
- Actual route: `codebuddy/codebuddy-cli/deepseek-v4.1-flash:max`; no fallback.
- Hermes sub-venue was not declared or used; this was a single Codex-chaired reviewer object.

## Conference Panel Review

Initial review found two P1 control-flow defects and several P2 provenance/UI gaps. Owner reproduced and repaired both P1s. Follow-up found no remaining P0/P1 and one new P2 in legacy route-receipt lookup; owner repaired it by reading the nested frozen route snapshot without changing schema or replaying Study A.

## Main-Venue Codex Review

Accepted repairs: skip ineligible/disabled fallback slots and continue the chain; expand the shared runner fallback set for comprehensive-AI task types; expose fallback thinking mode and inherit profile defaults; align the API with two backup slots; add expected/actual model and route endpoint to chunk receipts; explicitly label legacy inferred identity. Direct competitor-analysis providers that bypass `AiTaskRunner` remain a documented P2 migration item.

## Codex Independent Verification

Owner ran the consolidated affected suite: 217 passed, 18 deprecation warnings. Frontend production build passed with 1971 modules and the existing chunk-size warning. `git diff --check` passed. The isolated 5304 service restarted and reported MTPLX/Qwen/medium with OpenCode/max then CMS/max. Study A/B/C full-draft jobs were not replayed after the deterministic compatibility fix.

## Final Decision

Accept this routing batch for integration. Preserve lower-priority limitations in Trellis: current MTPLX service remains offline; direct competitor-analysis providers are not yet migrated to the shared runner; skipped fallback-slot reasons are not separately persisted; full product/Word/medical acceptance remains open.
