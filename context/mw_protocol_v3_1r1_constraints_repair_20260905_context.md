# Task Context: mw_protocol_v3_1r1_constraints_repair_20260905

Created: 2026-09-05 14:56:15
Objective: Task1R.1第二次有界纠错：修复仅表名列名相同但缺主键/唯一约束的数据库仍被接纳；保留历史失败执行包，按新正确生成的执行包留存独立回归与交接。此前worker已明确terminal且验收失败，使用同一原session，不重派unknown。
Task type: `finite_code_task`
Risk: `high`
Selected agent route: `zcode` / `GLM-5.3-Flash` / `max`

## Trigger Reason

Codex selected a bounded execution or review unit under the applicable task contract. Record the concrete delegation benefit or independent-review requirement; step count and file format alone are not triggers.

## Source Of Truth

- TODO: Add authoritative local files, extracts, datasets, screenshots, URLs, or user-provided materials.
- Do not add production paths unless the user has explicitly authorized reading them for this task.

## Scope

- In scope: TODO
- Out of scope: TODO

## Success Criteria

- TODO

## Risk Boundaries

- Do not write to production paths until Codex review gate passes and writable paths are explicit.
- The delegated agent is not final authority; Codex owns verification and acceptance.

## Timeout Policy

- Do not mark the delegated agent failed for slow response alone.
- For complex or artifact-heavy work, wait and poll generously; use conference mode when multiple independent model perspectives are needed.
- Failure requires terminal error, provider exhaustion/rate limit after controlled retry, empty/truncated retry output, or no progress after hard wait plus one retry.
- A provider catalog/auth/transport preflight is diagnostic, not a live capability verdict: timeout, auth refresh failure, malformed output, or a stale/incomplete catalog must be recorded and followed by one real route attempt. Explicit user-selected routes are not blocked merely because the catalog does not list them; only a missing executable or native transport boundary may stop before that attempt.

## Loop Log

- 2026-09-05 14:56:15: Task initialized by `tools/hermes_workflow_guard.py init-task`.
