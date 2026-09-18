# Codex Conference Review: mw_protocol_v3_1r1_fresh_20260905

Date: 2026-09-05

## Verdict

REVISE for task acceptance. Review returned; conditional READY is not adopted because independent executable counterexamples disprove complete fail-closed/atomic-batch coverage.

## Boundary Compliance

Reviewer checked the four frozen hashes, used temporary databases and preserved product sources. Same GLM family, different model and fresh context; no stronger model diversity claimed.

## Participant Outputs Reviewed

evidence_single_object.md, initial ZCode/GLM-5.3:max route, terminal success/no fallback. Runner report records104 focused and1344+101 full-suite passes, plus six additional probes. Reviewer's test-branch masking finding agrees with Codex.

## Conference Panel Review

Single-object packet, no chair declared. Hermes is not assigned by this route. Positive recommendation is advisory, not task closure.

## Main-Venue Codex Review

Five independent Codex failing cases remain: foreign schema_version0/1 adoption; mutation outside transaction survives rollback; caught second event SQL failure commits first event; :memory: product path accepted. Contract requires atomic event batches even when caught by caller. Caller convention does not justify silent durable writes outside rollback. Reviewer's empty-version-table probe does not cover a foreign populated version table.

## Codex Independent Verification

Codex read all adapter/new tests and reproduced1344+101 baseline and5red probes in runs/mw_protocol_v3_1r1_codex_20260905/. No browser/Word/product-model/production acceptance performed here. Add correct first-failure branch tests, reject naive datetime silently reinterpreted, correct narrow WAL commentary. Driver-error envelope goes to mandatory1R.3 work; env-enabled/default-off composition remains1R.2, not silently superseded by a function route.

## Final Decision

Same-session worker repair, then independent verification. Preserve initial reports and hashes as history; no cleanup. 1R.2 blocked on1R.1 acceptance, not on reviewer's confidence.

## Subsequent dispositions — historical verdicts above retained

Second targeted review repair_verification returnedNOT_READY426.636s with executableR1forwardmigration andR2partialclaim findings; currentv1guardfixesverified. Codex reproducedbothobservations, thenperformedboundedinline red-first remediation in twofiles. Third targeted final_storage_verification returnedREADY167.816s on hashes18770a1c.../6710dd96..., reproducing140focused/1372+101full/2ownclosureprobes. ExactGLM-5.3:maxidentity and before/afterhashes verified; nofallback. Codexreran2closureprobesPASS0.28s. FinalTask1R.1 acceptance is reviews/codex_mw_protocol_v3_1r1_storage_gate_20260905.md; originalreportsandobservationalprobeassertionsunchanged. No product/1R.2acceptance implied.
