# Codex Main-Venue Plan: mw_protocol_v3_userflow_review_20260905

Date: 2026-09-05
Objective: 只读交叉审阅医学写作用户主线的实际前后端接线、恢复与确认语义，给出可复现缺陷及Phase5R/6R/7R建议；不运行服务、浏览器、产品模型，不修改源码；与Task1R.1存储修复分离。

## Task Decomposition

One read-only user-flow/code review, separate from active SQLite repair. No new product implementation outside serial Plan gates. Codex integrates concrete findings into additive Plan and challenges their source evidence.

## Source Packet

See conference context for exact read boundaries, immutable Plan v2 + approved compatibility amendment, current baseline review and actual frontend/backend callers. No real patient artifacts, live runtime or credentials.

## Participant Assignments

| Role | Provider | Model | Output |
|---|---|---|---|
| `general_single_object` | `zcode` | `GLM-5.3` | `runs/conference/mw_protocol_v3_userflow_review_20260905/general_single_object.md` |

## Conference Panel Coordination

- No sub-venue chair. Codex leads the assigned panel directly.

## Main-Venue Review

- Codex performs the final synthesis and acceptance.
- This conference mode has no Reasonix second-review role.

## Timeout And Retry Tracking

Initial declared GLM-5.3:max pass pending dispatch after preflight. Retain runner lineage; no fixed-interval redispatch, cleanup or archive.

## Codex Verification Checklist

Verify each actionable finding against current source and deterministic reproduction. Do not equate code review with browser/Word inspection. Fold accepted additions into Phase5R/6R/7R gate tests without expanding into a new platform.
