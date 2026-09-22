# Conference Metrics: mw_protocol_v3_corpus_fallback_review_20260923

Date: 2026-09-23

| Role | Provider | Model | Status | Duration | API calls | Tokens | Result |
|---|---|---|---|---:|---:|---:|---|
| `general_single_object` | `zcode` | `GLM-5.3-Flash` | completed, same session | ~26.4 min across 3 model rounds | 3 model rounds | ~8.1k estimated input+output | initial REVISE; owner repaired two findings; follow-up PASS |

## Timeout And Retry Evidence

- Session: `sess_aa7ce14d-eeba-45d2-af67-42f549e3b528` for every round.
- Recorded round durations: 1059.344s, 279.612s, and 243.676s.
- No fallback, terminal failure, truncation, or empty output. The owner preserved the same session through silent intervals.
- Runtime receipt verifies ZCode with exact `GLM-5.3-Flash` model and `max` effort.

## Quality Decision

PASS after repairs. Independent review materially improved the batch by finding route-option drift and optional-fallback freeze failure. Same-session verification and owner regressions close both findings.
