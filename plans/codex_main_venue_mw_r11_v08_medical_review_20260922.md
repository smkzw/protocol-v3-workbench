# Codex Main-Venue Plan: mw_r11_v08_medical_review_20260922

Date: 2026-09-22
Objective: Fresh independent medical review of Study A v0.8 full-draft candidate: assess all 85 sections for consistency with embedded confirmed facts, unsupported medical or operational rules, decision-card quality, true source gaps, evidence relevance, user cognitive load, and whether the candidate can proceed toward user review; do not modify or adopt the artifact.

## Task Decomposition

1. Freeze v0.8 by path and SHA and verify deterministic coverage/evidence counts.
2. Use a fresh model identity different from the product generator; prohibit mutation and adoption.
3. Review every section, all decisions and all source gaps against embedded confirmed facts.
4. Codex verifies each critical/high finding directly and separates generator defects from absent project inputs.
5. Repair the smallest coherent generator rule or candidate scope, rerun only when evidence justifies it, and keep the artifact outside Word until medical review passes.

## Source Packet

- `runs/requirements_v2_20260919/f12_20260921/three_studies/isolated_runtime/medical_writing_full_drafts/proj_user_8a5a00cb014a/mwjob_cffd00bfa3697e3b95523084/full-draft.json` (SHA-256 `767923242f5cc7ca95837e67a68322990a14b2b7a1512793ccf0ce9023259133`).
- `plans/protocol_v3_fork_execution_20260921/CLINICAL_CONTENT_CONTRACT.md`.
- `plans/protocol_v3_fork_execution_20260921/03_PRD.md`.
- `runs/conference/mw_r11_v05_medical_review_20260922/evidence_single_object.md` for defect-closure comparison only.

## Participant Assignments

| Role | Provider | Model | Output |
|---|---|---|---|
| `evidence_single_object` | `grok-build` | `grok-4.7` | `runs/conference/mw_r11_v08_medical_review_20260922/evidence_single_object.md` |

## Conference Panel Coordination

- No sub-venue chair. Codex leads the assigned panel directly.

## Main-Venue Review

- Codex performs the final synthesis and acceptance.
- This conference mode has no Reasonix second-review role.

## Timeout And Retry Tracking

- Hard wait: 7200 seconds. Same-session follow-up only if the complete 85-section audit or evidence is incomplete.
- Record actual route/session, fallback, terminal state and whether the output was incorporated.

## Codex Verification Checklist

- Confirm exact artifact SHA, 85/85 coverage, 70/3/12 status split, 4 decisions and 407 evidence bindings.
- Verify all critical/high findings against actual text and evidence.
- Check prior v0.7 defects and remaining v0.5 defects: pre-confirmation prose, duplicate cards, estimand inconsistency, unsupported SUSAR definition and semantic fact-path misuse.
- Check whether 7 source gaps are true blockers and whether any complete sections still invent project rules.
- Assess whether 21 required-review sections create avoidable user burden.
- Do not equate medical review with Word, browser, professional or submission acceptance.
