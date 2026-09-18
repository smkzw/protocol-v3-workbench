# Codex Main-Venue Plan: mw_protocol_v3_2r1_fresh_20260905

Date: 2026-09-05
Objective: Fresh read-only review of frozen Task2R.1 typed runtime, actual three-case recovery and concurrent decision semantics; identify concrete functional defects and minimal repairs. No product calls or source writes.

## Task Decomposition

One fresh independent review of the frozen 2R.1 implementation. No source edits
while review runs. Codex will integrate concrete findings, then bounded repair
and same-reviewer revalidation; no stage pause or task closure yet.

## Source Packet

See conference context for exact original artifacts and isolated test environment.
Do not consume execution reports as acceptance arguments.

## Participant Assignments

| Role | Provider | Model | Output |
|---|---|---|---|
| `general_single_object` | `opencode-go` | `muse-spark-1.3-contributor` | `runs/conference/mw_protocol_v3_2r1_fresh_20260905/general_single_object.md` |

## Conference Panel Coordination

- No sub-venue chair. Codex leads the assigned panel directly.

## Main-Venue Review

- Codex performs the final synthesis and acceptance.
- This conference mode has no Reasonix second-review role.

## Timeout And Retry Tracking

Awaiting initial dispatch after prompt preflight. Healthy runner is awaited on
the same handle; no fixed redispatch, no archive post-command.

## Codex Verification Checklist

Inspect artifacts, run deterministic counterexamples and regressions; confirm
actual receipt identity, synthesize reviewer findings, repair then reverify.
