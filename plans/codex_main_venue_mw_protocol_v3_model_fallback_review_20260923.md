# Codex Main-Venue Plan: mw_protocol_v3_model_fallback_review_20260923

Date: 2026-09-23
Objective: 只读独立审阅Protocol v3综合AI用户自选provider/model/思考强度与MTPLX到OpenCode Go再到CMS Router的2+1自动降级实现；检查错误分类、身份/effort回执、全文chunk provenance、旧任务兼容、UI可理解性和测试缺口。不得修改源码。

## Task Decomposition

1. Reviewer independently traces persisted settings through policy resolution and both execution entry points.
2. Reviewer challenges fallback error classification, lineage/provenance, effective identity and effort, and old frozen route compatibility.
3. Reviewer inspects the user-facing selector/fallback editor for misleading states or missing controls.
4. Reviewer checks whether tests and Study A/B/C evidence support the stated claims, reporting concrete findings with line references.
5. Codex verifies every finding against current source, applies only justified repairs, then reruns the affected batch once.

## Source Packet

The authoritative file list and boundaries are in `context/mw_protocol_v3_model_fallback_review_20260923_conference_context.md`. Runtime acceptance artifacts are evidence only. Existing unrelated dirty work is preserved.

## Participant Assignments

| Role | Provider | Model | Output |
|---|---|---|---|
| `evidence_single_object` | `codebuddy-cli` | `deepseek-v4.1-flash` | `runs/conference/mw_protocol_v3_model_fallback_review_20260923/evidence_single_object.md` |

## Conference Panel Coordination

- No sub-venue chair. Codex leads the assigned panel directly.

## Main-Venue Review

- Codex performs the final synthesis and acceptance.
- This conference mode has no Reasonix second-review role.

## Timeout And Retry Tracking

- Start: 2026-09-23 01:07 CST.
- Keep the same session for any bounded follow-up; do not redispatch for latency alone.
- Record actual provider/model/effort, terminal state and whether fallback occurred after the runner returns.

## Codex Verification Checklist

- Confirm reviewer did not modify source.
- Reproduce each P0/P1/P2 finding directly from current code or reject it with evidence.
- Check all named tests and acceptance artifacts remain bound to current diff.
- Run `git diff --check`, the consolidated affected pytest set, and frontend production build after any repair.
- Do not call the overall Protocol v3 product complete from this bounded routing review.
