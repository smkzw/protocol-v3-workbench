# Codex Main-Venue Plan: mw_r11_full_draft_v03_review_20260922

Date: 2026-09-22
Objective: Independently review the frozen Study A Protocol v3 full-draft v0.3 candidate and current v0.2 review projection against authoritative StudyDefinition revision 8 and AI-lead product acceptance. Determine adoption readiness, unsupported project-specific rules, cross-section inconsistency, excessive repetition, missing submission content, and exact remediations. Review only; do not modify source or runtime artifacts.

## Task Decomposition

1. Verify candidate and StudyDefinition identities from the readable source packet.
2. Review all 85 sections for source fidelity, section sufficiency, contradictions, repeated design facts, and fixed conduct rules unsupported by revision 8.
3. Review the 18-card mandatory-confirmation projection and full-draft review presentation against the AI-lead user goal.
4. Return an adoption verdict and prioritized, minimal corrections. Codex independently verifies findings before any repair or adoption.

## Source Packet

- `context/mw_r11_full_draft_v03_review_20260922_source_packet.md` (all 85 sections plus StudyDefinition revision 8 extract).
- Frozen candidate SHA-256 `c2e98124598aa71a2e36eedb173cd24163d8a8504f41d9996a963cf241192da9`.
- Current review projection `protocol_full_draft_review_v0_2`, 18 mandatory cards.

## Participant Assignments

| Role | Provider | Model | Output |
|---|---|---|---|
| `evidence_single_object` | `codebuddy-cli` | `deepseek-v4.1-flash` | `runs/conference/mw_r11_full_draft_v03_review_20260922/evidence_single_object.md` |

## Conference Panel Coordination

- No sub-venue chair. Codex leads the assigned panel directly.

## Main-Venue Review

- Codex performs the final synthesis and acceptance.
- This conference mode has no Reasonix second-review role.

## Timeout And Retry Tracking

Record runner start/end time, exact route identity, session id, terminal state, fallback/retry reason if any, and whether each finding was incorporated.

## Codex Verification Checklist

- Confirm the readable packet hash and raw candidate hash.
- Reproduce material section findings from the frozen artifact.
- Keep deterministic artifact integrity, clinical content acceptance, and browser usability acceptance separate.
- Do not adopt the candidate until material content findings and the 18-card workflow are resolved.
