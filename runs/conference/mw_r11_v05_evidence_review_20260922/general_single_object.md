All checks are done — verification ran at HEAD, which is exactly the frozen commit, and the repo remains unmodified (only pre-existing untracked `runs/` artifacts show in git status). Here is my complete conference report.

---

# Conference Participant Output: mw_r11_v05_evidence_review_20260922 - general_single_object

## Boundary Check

- Worked only inside the runner-bound workspace plus `/tmp` (disposable deps at `/tmp/mw_r11_review_deps`, probe at `/tmp/mw_r11_v05_probe/probe_final_reuse_gate.py`). No repo file was created or modified; the runner-managed report path was not written; the historical v0.4 artifact was opened read-only. No product model was invoked and no medical prose quality was judged. No final clinical/regulatory/adoption acceptance is claimed; Codex remains final authority.

## Independent Work Product

**Verdict:** the commit achieves its three stated properties, with **one Medium defect** (M1, reproduced by probe), **two Low items** (L1 robustness, L2 test gaps), and one trust-model observation. Nothing found blocks the planned isolated v0.5 Study A generation; M1 is worth one guard clause before that run.

### Answers to the assigned questions

1. **Restart resolvability without cross-chunk ID ambiguity — YES (with the M1 caveat).** Each section persists its own `evidence_bindings` (span_id, source_id, locator, quote, quote_sha256) built from the same chunk response (`medical_writing_full_draft.py:895-898` via `:505-539`); the ID map is scoped to one provider output (`:516-520`). After persistence, span IDs are never used as cross-chunk lookup keys: the merge gate (`:950-959`), chunk-reuse gate (`:670-719`, schema/digest/coverage/chain), and adopt gate (`:1127-1137`) each validate each section's own bindings against the union of `source_bindings`, and the quote hash (`:558-565`) detects quote tampering. Generation-time inputs are already strict: gateway enforces span-ref resolvability and uniqueness (`ai_gateway.py:2016-2026`), the runner enforces source membership, exact locator equality, non-empty quote, and quote ⊆ `text_preview` (`ai_task_runner.py:2741-2774`), and 8aabfea's demotion (`ai_task_runner.py:882-944`) removes dangling refs before validation.
2. **Damaged chunks — correctly rejected; damaged finals — reuse gap (M1).** A chunk with an emptied `evidence_bindings` is not reused and the chunk is regenerated (unit test `tests/test_medical_writing_full_draft.py:679-698`, and my probe CONTROL: model re-invoked, rebuilt final chain resolvable). But a v5 **final** whose JSON is still valid while its chain is broken is re-persisted as a completed candidate by the early final-reuse gate (`medical_writing_full_draft.py:794-834`) — see M1. Adoption of either is refused (`:1125-1137`).
3. **v3/v4 readable but non-adoptable — YES.** `read_artifact` accepts {v5, v3, v4} (`:1086-1090`) and never runs the chain check on legacy files; `_apply_review_policy` flags `legacy_read_only=true` / `adoption_ready=false` (`:610-612`); `adopt` (`:1125-1126`) and `resolve_decision` (`:1292-1295`) reject legacy. Confirmed against the real v0.4 artifact: `schema_version=protocol_full_draft_artifact_v4`, 85 sections carrying `evidence_span_ids` but no `evidence_bindings` (272 distinct span IDs; 104 source-level bindings only). Old jobs fail closed under v5 code: descriptor v6 participates in the digest (constant injected at `:264` before digest at `:283`), so a resumed v0.4 job errors "全文初稿上下文已变化” (`:779-780`); v4 chunks fail the schema check (`:690`); the business key derives from the digest, so no job reuse. The untouched v0.4 artifact stays a pure historical record.
4. **Tests reproduced:** 115 passed (full-draft 24 + gateway 53 + runner 38), matching the stage record, run at HEAD under python3.12 with deps installed into a disposable `/tmp` target (repo has no venv; system interpreters lack `cryptography`). Module import doubles as the compile check.

### Findings by severity

**M1 (Medium) — early final-reuse gate re-persists a v5 final without evidence-chain re-validation.** `medical_writing_full_draft.py:794-834` accepts an existing final on schema/job/project/digest/coverage alone. Probe (real service classes, temp dir): after emptying one section's `evidence_bindings` in `full-draft.json`, re-running the job returned `error=''`, phase `persisted_candidate`, message “已复用已持久化全文初稿 2/2 个章节候选”， with no regeneration, and sealed the tampered bytes into the new locator (`output_hash` == sha256 of tampered file). `read_artifact` then serves it and `coverage.adoption_ready` recomputes to `true` (`:612` ignores chain state), while only `adopt` rejects (“全文初稿章节证据链不完整，未采纳”). Consequences: inconsistent with the sibling paths and with the stage record's “合并最终候选和采纳前再次核对完整证据链”； a damaged-but-valid final is stuck (every rerun short-circuits at the same gate, and an already-completed job row is returned by `create_or_reuse`, so recovery needs manual file deletion); a medical review cycle can be spent on a permanently unadoptable candidate. Not an adoption-safety breach — the last-line gate holds. **Remediation:** inside the gate, run the same `_section_evidence_is_resolvable` check over `existing_final["sections"]` vs `existing_final["source_bindings"]` and fall through to the chunk loop on failure (valid chunks are still reused; no model cost for good chunks); optionally fold chain validity into the read-time `adoption_ready`.

**L1 (Low) — defensive raise escapes `run_job` as retryable.** The `_evidence_bindings_for_section` call at `:895` sits outside the `try` at `:871-874`; if it ever raised, `medical_writing_durable_jobs.py:1156-1160` converts it into a retryable failure, burning attempt 2 of `max_attempts=2` on a deterministic violation with a raw `RuntimeStoreError` message. Unreachable today given the gateway/runner gates above — a latent inconsistency only. Wrap the binding loop in the same `DurableJobResult(error=…, retryable=False)` pattern.

**L2 (Low, test gaps).** (a) No test proves two chunks with identical span IDs but different quotes both survive merge — the exact invariant this commit exists for (structurally satisfied; undocumented). (b) No test covers the early-reuse gate with a damaged final (M1). The collision premise is empirically real: in the v0.4 artifact, 15 span IDs are cited under two distinct runs, e.g. `es_sd_intervention` under `airun_20260921192454_953aa998` and `airun_20260921201003_c064532d`.

**Observation (not a defect).** These checks defend against partial corruption, torn writes, restore-from-backup, and provider regressions; a deliberate local attacker can rewrite bindings and `source_bindings` consistently. That matches the existing unsigned hash-locator model; no change requested.

## Evidence And Assumptions

- Diff and code: `git show 58639c7`; `medical_writing_full_draft.py:48-55, 505-568, 670-719, 794-834, 895-898, 946-999, 1086-1091, 1116-1137, 1291-1295`; `ai_gateway.py:1880-1905, 2016-2026`; `ai_task_runner.py:882-944, 2732-2774, 2880-2978`; `medical_writing_durable_jobs.py:303-339, 1154-1199`.
- Artifacts: v0.4 `…/mwjob_96ee70138c21a86568eb3f3d/full-draft.json` and `chunks/chunk-0001-…json` (both read-only; v4 schemas, no bindings).
- Runs: 115 tests reproduced (24/53/38); probe outputs quoted above; probe script at `/tmp/mw_r11_v05_probe/probe_final_reuse_gate.py` for reproduction.
- Assumptions: the probe bypasses gateway validation exactly like the unit tests do (compliant fake outputs), so M1 isolates the gate logic; on the real path the pre-validation gates cited above apply upstream. HEAD equals the frozen commit; reviewed source files show no working-tree modification (only pre-existing untracked `runs/` entries in git status).

## Risks, Gaps, And Verification Needs

- M1 leaves a narrow stuck-state path (damaged-yet-valid v5 final) that wastes a review cycle and needs manual cleanup; adoption safety itself is intact.
- Residual for the real v0.5 run (belongs to the later run, not this review): verify all 85 sections' bindings resolve on the actual artifact, and hold the fresh medical conference before any adopt — consistent with the stage record and the plan's checklist.
- `evidence_summary` counts in `_review_metadata` (`:470-473`) key span IDs unstripped while the new helper strips — pre-existing, unreachable given runner validation; noting for completeness only.

## Recommended Next Step

Fix M1 as one small batch before the real v0.5 run: add the chain re-check + fall-through in the early-reuse gate (`:794-834`), add the two missing regression tests (cross-chunk duplicate span IDs; damaged-final reuse), optionally harden L1, then rerun the 115-test set and proceed to the isolated Study A v0.5 generation as planned. Bounded questions for Codex: (1) on chain failure in the gate, fall through to regeneration (my recommendation) or fail the job non-retryably? (2) should read-time `coverage.adoption_ready` also reflect chain validity, or stay decision/legacy-only with `adopt` as sole authority? (3) confirm M1 belongs in this batch rather than a follow-up — the reuse gate predates this commit, but the fix is one guard clause and v5's purpose is durable auditable provenance.
