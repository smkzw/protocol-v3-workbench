# Codex Main-Venue Plan: mw_r11_v05_evidence_review_20260922

Date: 2026-09-22
Objective: Independently review frozen commit 58639c7 for clinical draft evidence provenance, recovery compatibility, and adoption safety; report only evidence-backed defects and do not modify source.

## Task Decomposition

1. Freeze commit `58639c7` and preserve the unmodified historical v0.4 artifact.
2. Ask one fresh reviewer to inspect the exact diff, complete affected definitions, tests, and v0.4 artifact shape.
3. Owner verifies every reported defect directly against source and runs only decisive focused checks.
4. Repair confirmed defects as one coherent batch, then rerun the affected regression set.
5. Only after engineering acceptance, run a new v0.5 Study A job and hold separate fresh medical review of that artifact.

## Source Packet

- `git show 58639c7` and parent `8aabfea`
- affected implementation and three focused test modules listed in the conference context
- v0.5 stage record and immutable v0.4 candidate listed in the conference context

## Participant Assignments

| Role | Provider | Model | Output |
|---|---|---|---|
| `general_single_object` | `zcode` | `GLM-5.3-Flash` | `runs/conference/mw_r11_v05_evidence_review_20260922/general_single_object.md` |

## Conference Panel Coordination

- No sub-venue chair. Codex leads the assigned panel directly.

## Main-Venue Review

- Codex performs the final synthesis and acceptance.
- This conference mode has no Reasonix second-review role.

## Timeout And Retry Tracking

- Initialized 2026-09-22 04:51 CST. Runner hard wait is 7200 seconds; slow output remains pending.
- Record actual route, terminal state, fallback, session identity and incorporation after completion.

## Codex Verification Checklist

- Confirm reviewer inspected the frozen diff rather than current unstaged work.
- Verify each finding with exact file/line or artifact key evidence.
- Check cross-chunk duplicate span IDs, empty evidence for source gaps, source membership, quote hash, legacy read-only behavior, and adoption rejection.
- Reject speculative redesign without a current consumer or demonstrated defect.
- Do not treat reviewer PASS as medical or product acceptance.
