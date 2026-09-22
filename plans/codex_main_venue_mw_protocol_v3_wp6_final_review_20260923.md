# Codex Main-Venue Plan: mw_protocol_v3_wp6_final_review_20260923

Date: 2026-09-23
Objective: 对冻结提交e8966d5及WP6真实证据做独立只读工程与医学接受复核；判断A/V/B验收结论、工作稿医学边界、Office/Word所有权、模型fallback和重复采用修复是否有P0-P4问题，不修改源码。

## Task Decomposition

1. Verify frozen source and current tests do not regress semantic/Office ownership.
2. Verify real HTTP, model, browser and native Word evidence at their actual evidence layer.
3. Sample the Study C working draft for medical plausibility and source-gap honesty.
4. Report P0-P4 findings and recommend exact remaining acceptance status; do not modify artifacts.

## Source Packet

See `context/mw_protocol_v3_wp6_final_review_20260923_conference_context.md`. Runtime secret files and live services are excluded.

## Participant Assignments

| Role | Provider | Model | Output |
|---|---|---|---|
| `general_single_object` | `zcode` | `GLM-5.3-Flash` | `runs/conference/mw_protocol_v3_wp6_final_review_20260923/general_single_object.md` |

## Conference Panel Coordination

- No sub-venue chair. Codex leads the assigned panel directly.

## Main-Venue Review

- Codex performs the final synthesis and acceptance.
- This conference mode has no Reasonix second-review role.

## Timeout And Retry Tracking

Start after source commit `e8966d5`; use one runner invocation with 7200-second hard wait and preserve the same session for any follow-up.

## Codex Verification Checklist

- Independently inspect every cited evidence file and reviewer claim.
- Do not convert screenshot timeout, historical screenshots, fallback success, or a Word open/save into broader acceptance than demonstrated.
- Repair only reproducible source defects; rerun the affected family and complete backend/frontend regression before final integration.
