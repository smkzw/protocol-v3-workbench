# RegimenProposalCard UI — worker_01 detailed report

Task: `mw_protocol_v3_regimen_card_ui_20260913`  
Role: bounded execution worker (not final acceptance)  
Component status: **implemented and unit-tested; not mounted by owner**

## Artifacts created

| File | SHA256 |
|---|---|
| `frontend/src/features/medical-writing/protocol-workbench/RegimenProposalCard.jsx` | `bb0aac588e38223e3e540e112d8239c74915415ceaed95f30a8599490e1cabbb` |
| `frontend/src/features/medical-writing/protocol-workbench/RegimenProposalCard.css` | `f23de88d606019a1432fd227c0aaa186a536ef8858d42a5e397ad964cdcea59d` |
| `frontend/src/features/medical-writing/protocol-workbench/RegimenProposalCard.test.jsx` | `b3d2c69d72940345ee5701b9c612e9d891f97bb62aac4e84eb5c95cc96d91c0c` |

Scratch logs also under `runs/execution/mw_protocol_v3_regimen_card_ui_20260913/scratch/`.

## Contract sources used

- Snapshot authority (not live owner-mutable sources):
  - `runs/execution/mw_protocol_v3_regimen_card_ui_20260913/snapshot/clinical_worker.py`
  - `runs/execution/mw_protocol_v3_regimen_card_ui_20260913/snapshot/recommendations.py`
- Adjacent UI patterns:
  - `ProtocolIntakeWorkspace.jsx` / `.css` / `.test.jsx`
  - `sourceRoleLabels.mjs`
- Vitest invocation pattern from `frontend/tests/protocol_v3_test_inventory.mjs`:
  - `vitest run --config vite.config.mjs --environment jsdom <paths>`

## Public API

```js
export function RegimenProposalCard({
  proposal,
  onConfirm,
  busy = false,
  error = "",
  sourceDownloadUrl,
})
```

`proposal` is treated as a `read_regimen_response` snapshot: `status` / `coverage` / `regimen` / `questions`.  
The card renders listed `periods` × `arms` via `schedules` only. It does not infer missing cells as 停药/不适用, does not pick first candidates, and does not write localStorage / API / DecisionRecord / confirmed state.

## Behavior covered

- One card shows all listed period/arm schedule units; loading + maintenance both visible with dose/volume units preserved.
- Chinese UI: title「剂量方案」, red tag「监管答辩级·需确认」, status「建议，尚未确认」.
- Kind/support enums localized; locator/hash/internal English enums not shown; historical support never labeled 已批准.
- Collapsible evidence; quotes verbatim; one download link per `source_artifact_id` when `sourceDownloadUrl(id)` returns a non-empty string; no forged URL.
- Confirm button「确认这套给药方案」calls `onConfirm(proposal)` only on explicit click; sync double-click guarded; disabled while busy / confirming / missing callback / status ≠ `ready_for_review` / empty regimen / open questions or unresolved_questions (those items are listed).
- Confirm failure keeps full card, shows readable Chinese error, no auto-retry, no optimistic saved state; external `error` also shown.
- Replacing `proposal` clears prior confirm error and ignores stale rejected promises.

## Tests

### Red (before component)

Command:

```bash
cd frontend && ./node_modules/.bin/vitest run --config vite.config.mjs --environment jsdom \
  src/features/medical-writing/protocol-workbench/RegimenProposalCard.test.jsx
```

Log: `scratch/vitest-red.log`  
Result: FAIL — `Failed to resolve import "./RegimenProposalCard"` (expected red).

### Green (after implementation)

Same command.  
Log: `scratch/vitest-green.log`  
Result: **9 passed / 9** (exit 0).

### Adjacent (allowed, not full-repo)

Command:

```bash
cd frontend && ./node_modules/.bin/vitest run --config vite.config.mjs --environment jsdom \
  src/features/medical-writing/protocol-workbench/RegimenProposalCard.test.jsx \
  src/features/medical-writing/protocol-workbench/ProtocolIntakeWorkspace.test.jsx \
  src/features/medical-writing/protocol-workbench/ProtocolSourceIntake.test.jsx
```

Log: `scratch/vitest-adjacent.log`  
Result: **3 files / 38 tests passed** (exit 0). No old expectations weakened; no xfail added.

## Verification not performed (owner scope)

- Browser visual acceptance / mounting into ProtocolIntakeWorkspace or any live route.
- Backend CAS confirmation path.
- Full frontend inventory / full-repo test run.
- No service start, no dependency install, no git commit.

## Limits / boundaries honored

- Only the three authorized frontend files plus `scratch/` logs and this REPORT.md were written.
- No changes to other source/tests/manifest/plans/runtime libraries.
- No live/监查/8910/external SOP touch.
- No recursive dispatch, conference, web search, product-model calls, cleanup, or final acceptance claim.
- This component remains **unmounted**; owner integrates and performs browser acceptance.

## Worker note for runner

Do not treat this report as final product acceptance. Runner-managed path `worker_01.md` was not written by this worker.
