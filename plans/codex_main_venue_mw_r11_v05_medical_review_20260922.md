# Codex Main-Venue Plan: mw_r11_v05_medical_review_20260922

Date: 2026-09-22
Objective: Fresh independent medical review of Study A v0.5 full-draft candidate: assess source-bounded scientific content, cross-section consistency, unsupported operational rules, decision-card quality, source gaps, and whether any prose may proceed toward user review; do not modify or adopt the artifact.

## Task Decomposition

1. Freeze the completed v0.5 artifact by path and SHA-256; verify all evidence bindings deterministically.
2. Use a fresh model identity different from the product generator and prohibit artifact mutation/adoption.
3. Require complete 85-section coverage, evidence-specific findings and an explicit user-review boundary.
4. Codex verifies every critical/high finding directly against the artifact and decides the repair batch.
5. Repair the generator or scoped candidates rather than manually polishing a flawed artifact; rerun only affected sections when the contract permits.

## Source Packet

- Frozen v0.5 artifact and SHA in conference context.
- Embedded StudyDefinition, target sections, source bindings, evidence quotes and decision cards.
- `plans/protocol_v3_fork_execution_20260921/CLINICAL_CONTENT_CONTRACT.md`
- `plans/protocol_v3_fork_execution_20260921/03_PRD.md`
- v0.5 engineering provenance record and review listed in context.

## Participant Assignments

| Role | Provider | Model | Output |
|---|---|---|---|
| `evidence_single_object` | `zcode` | `GLM-5.3-Flash` | `runs/conference/mw_r11_v05_medical_review_20260922/evidence_single_object.md` |

## Conference Panel Coordination

- No sub-venue chair. Codex leads the assigned panel directly.

## Main-Venue Review

- Codex performs the final synthesis and acceptance.
- This conference mode has no Reasonix second-review role.

## Timeout And Retry Tracking

- Hard wait: 7200 seconds. Same-session follow-up only if coverage or evidence is incomplete.
- Generated CodeBuddy primary was intentionally not dispatched because it matched the product generator model; this quality-driven de-duplication is recorded in context.

## Codex Verification Checklist

- Confirm artifact SHA and 85/85 coverage.
- Verify all cited critical/high findings against section text and evidence binding.
- Check that missing external evidence is not converted into invented requirements.
- Separate medical corrections from statistics/PV/operations questions.
- Confirm no source/runtime files changed and no adoption endpoint was called.
- Do not turn medical-review PASS into Word, browser, formal professional, or submission acceptance.
