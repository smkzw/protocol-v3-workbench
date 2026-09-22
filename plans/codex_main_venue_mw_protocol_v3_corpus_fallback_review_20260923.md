# Codex Main-Venue Plan: mw_protocol_v3_corpus_fallback_review_20260923

Date: 2026-09-23
Objective: Independently review the frozen Protocol v3 corpus-analysis provider fallback implementation. Check legacy frozen-route compatibility, immutable logical-work identity, exact provider/model/thinking/effort binding, allowed fallback error classes, prevention of fallback on invalid request/content/identity errors, persistence and audit provenance, and focused tests. Review only; do not modify source.

## Task Decomposition

1. Freeze and inspect the current uncommitted corpus-analysis fallback diff.
2. Ask one independent reviewer to challenge compatibility, identity, fallback classification, provenance, and tests without modifying source.
3. Codex verifies every material finding against source and focused tests, repairs accepted defects, and reuses the same reviewer session for a targeted follow-up when needed.
4. Run the concentrated corpus/pipeline regression and Protocol v3 suite before commit.

## Source Packet

- `services/api/app/medical_writing_corpus_analysis_ai.py`
- `services/api/app/main.py`
- `services/api/app/ai_gateway.py`
- `services/api/app/ai_runtime_settings.py`
- `tests/test_medical_writing_corpus_analysis_ai.py`
- Current git diff restricted to those paths

## Participant Assignments

| Role | Provider | Model | Output |
|---|---|---|---|
| `general_single_object` | `zcode` | `GLM-5.3-Flash` | `runs/conference/mw_protocol_v3_corpus_fallback_review_20260923/general_single_object.md` |

## Conference Panel Coordination

- No sub-venue chair. Codex leads the assigned panel directly.

## Main-Venue Review

- Codex performs the final synthesis and acceptance.
- This conference mode has no Reasonix second-review role.

## Timeout And Retry Tracking

- Start: 2026-09-23 05:04 CST.
- Hard wait: 120 minutes. Preserve and continue the same session for targeted follow-up.
- Completed in session `sess_aa7ce14d-eeba-45d2-af67-42f549e3b528`; three model rounds, no fallback.

## Codex Verification Checklist

- [x] Required reviewer returned a complete report with runtime identity evidence.
- [x] Legacy route payload behavior remains unchanged when no fallback chain is present.
- [x] Only approved transient failure classes advance to the next frozen route.
- [x] Declared and effective route provenance is truthful and persisted.
- [x] Focused and broader Protocol v3 tests pass, with unrelated failures identified separately.
