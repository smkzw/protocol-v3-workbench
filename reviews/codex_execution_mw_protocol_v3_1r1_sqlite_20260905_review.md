# Codex Execution Review: mw_protocol_v3_1r1_sqlite_20260905

## Verdict

REVISE. Initial candidate is not accepted. Independent main-agent probes reproduce foreign-schema adoption, mutation outside an active transaction surviving rollback, and a caught database write failure leaving half an event batch. Fresh reviewer returned conditional READY, overridden by these counterexamples. Findings consolidated and same-session worker repair dispatched using worker_01_followup_01.md; repair pending.

## Worker Outputs

worker_01 returned through ZCode/GLM-5.3-Flash:max, session sess_1eefde6c-2f6f-4bf3-9536-355e7e92cab9,1919.257s, one round/no fallback. Four allowed source/test files only. Actual linked SQLite3.53.4. Runner requested/response identity and max effort verified. Bridge tool count2 undercounts internal execution: exact-session read-only tool_usage query records69 completed operations+1 failed Edit. Do not claim runner token aggregate as whole-session cost.

Receipt corrections: report lists a non-existent Plan filename; exact-session Bash inputs show actual reads of the correct Plan v2 (040eb6...) sections40–190, not full Plan despite assigned full read. Report's48+24 case count is wrong: Codex JUnit confirms74 shared-backend cases+30 product cases=104. Source sqlite.py is1851lines, not ~1500. Worker used native Write/Edit despite explicit apply_patch-only instruction. Preserve original reports; bounded repair must reread required authority fully, use apply_patch and return exact evidence. These process deviations are not silently marked compliant.

## Manager Assessment

No manager assigned by current E03 route; Codex integrates. Hermes is not assigned. Fresh reviewer uses separate GLM-5.3:max context, excludes worker reasoning/conclusion.

## Codex Independent Verification

Read all1851lines of adapter and both new tests; selected.py diff inspected. Reproduced full tests/protocol_v3:1344passed+101subtests,2warnings,22.73s (runs/mw_protocol_v3_1r1_codex_20260905/full_candidate.xml). Additional acceptance_probes_red_v2.xml:4failed for three substantive defects. Initial red.xml also retained; its event probe first used too-short synthetic IDs and did not reach the target branch. Corrected IDs only, unchanged assertions; red_v2 reaches and proves SQL partial-batch failure.

Test coverage gap: TestEventStream.test_chain_violation_rejects_whole_batch prepends already-appended e1 for gap/prev_mismatch/duplicate_event_id/wrong_stream, so those cases stop at duplicate e1 rather than the named branch. Keep fixtures/expectations and add proper branch-specific negative cases. Do not rely on this nominal matrix as five distinct failure-path proofs.

Later additive probe: product config path=:memory: is accepted, opening volatile SQLite and losing schema when bootstrap closes the connection. acceptance_probes_red_v3.xml now has5failed across four substantive defects. Preserve earlier4-failure evidence. Reject special volatile paths before connection creation; do not confuse selected backend name with verified file-backed durability.

audit-execution reports ok=true for packet/route/result presence; it does not dispose the REVISE verdict, independent test failures or documented workflow deviations. No task acceptance is inferred from that mechanical audit.

## Cleanup Decision

No cleanup or archive authorized. Retain all initial reports, red/green evidence and runtime lineage. Task1R.1 stays open; no main/API/product activation.
