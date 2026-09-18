# Conference Metrics: mw_protocol_v3_1r1_fresh_20260905

Date: 2026-09-05

| Role | Provider | Model | Status | Duration | API calls | Tokens | Result |
|---|---|---|---|---:|---:|---:|---|
| `evidence_single_object` | `zcode` | `GLM-5.3:max` | Returned |597.797s|Not independently totaled|Runner usage160328; scope not whole-session cost verified|Conditional READY; Codex task REVISE|

## Timeout And Retry Evidence

Session sess_e31a1421-b58b-4d69-8025-7a0795fbc289,1round,returncode0,no fallback. Requested/effective agent/provider/model/effort match. No slow-provider failure or redispatch.

## Quality Decision

Original result retained. Main executable5-case red evidence overrides conditional READY. Reviewer branch-coverage and naive-time findings incorporated into bounded same-worker-session repair; task acceptance remains open. Mechanical workflow audit does not dispose failed tests.

## Targeted follow-up receipts

| Pass | Duration | Observed tools | Identity | Result |
|---|---:|---:|---|---|
| repair_verification |426.636s|22|zcode/GLM-5.3:max, sameverifier session,one round,nofallback|NOT_READY,R1/R2|
| final_storage_verification |167.816s|9|zcode/GLM-5.3:max, sameverifier session,one round,nofallback|READY limited1R.1;140focused,1372+101full,2closureprobes|

Both actualrequest/response identities verified. FinalreportSHA266cb45fb065134a48a5a1c16f55a3ca153d553a613c60b37a9a6ea9ddda5480. Codex separately reproducedclosureprobes and froze sourcehashes in finalstoragegate. Previous rows remain historical, not currentfailureclaims. This is fresh fromimplementationcontext, not a claimofdifferentmodel-family diversity or professionalapproval.
