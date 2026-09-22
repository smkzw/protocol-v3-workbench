# Execution Output: mw_r11_design_choices_20260921 - worker_01

## Boundary And Context Check

- Declared fallback honored: `openai-codex/gpt-5.6-luna`.
- Initial context and execution plan read.
- Scope respected:
  - Modified only `frontend/src/features/medical-writing/protocol-workbench/DesignElementsCards.jsx`.
  - Added only `frontend/src/features/medical-writing/protocol-workbench/DesignElementsCards.test.jsx`.
  - No backend, database, CSS, Office, generated, or production changes.
  - Did not read `HANDOFF_ROUND10.md`.
- Capability limitation: no browser/server, clinical/regulatory, or final rendered acceptance performed. Codex remains final authority.

## Work Performed

- Added real radio selection for primary objectives:
  - First option is visually preselected only.
  - User-selected index is sent as `selections.primary_objective`.
  - The confirm action remains explicit; no automatic confirmation.
- Added exact intent persistence and recovery:
  - Per-card pending intents are loaded from local storage on mount.
  - Existing intent is recovered before any new operation id is generated.
  - Unknown outcomes retain the original operation and expose a reconciliation action.
  - `424` configuration rejection retains the intent and offers explicit retry with the same intent.
  - Definitive `400/404/409/422` apply rejection clears only the active pointer while retaining the attempt record.
  - Recovery never automatically adopts a pending intent.
- Added confirmed-choice display:
  - Confirmed local records now retain `selections`.
  - A confirmed second objective remains visibly identified after remount.
  - Legacy confirmed records without a stored selection explicitly show that historical choice is unknown; the first proposal option is not presented as historical fact.
- Preserved existing owner changes: confirmed content remains visible, the primary endpoint remains critical, and basis labels remain compact.

## Artifacts And Evidence

- `frontend/src/features/medical-writing/protocol-workbench/DesignElementsCards.jsx`
  - Objective radio UI and selection display: lines 41–95.
  - Intent/confirmed local state: lines 144–181.
  - Receipt validation and confirmed selection retention: lines 214–254.
  - Recovery/adoption/retry flow: lines 316–441.
  - Card prop wiring: lines 467–472.
- `frontend/src/features/medical-writing/protocol-workbench/DesignElementsCards.test.jsx`
  - Second objective sends index `1`: lines 80–90.
  - Original pending intent survives remount without a second adoption: lines 93–123.
  - Confirmed objective remains visible instead of defaulting to option 0: lines 125–140.

Backend contract sources checked read-only:

- `services/api/app/protocol_workflow/api/design.py:467-488,516-552`
- `services/api/app/protocol_workflow/api/schemas.py:359-363`
- `services/api/app/protocol_workflow/agent2/design_adoption.py:178-218,221-255`
- `frontend/src/features/medical-writing/protocol-workbench/protocolWorkspaceApi.mjs:272-278`

Observed contract:

- The design-card adoption request requires `selections.primary_objective` as a strict integer within the proposal range.
- `primary_endpoint_confirmed: true` is the existing contract for the endpoint confirmation.
- Recovery is a read-only receipt lookup; `404` means no matching receipt was found.
- Mutation receipts contain revision, revision hash, definition, and effective decision, but do not echo the objective index. The frontend therefore retains the exact selection in its local intent/confirmed record and reports unknown history when that record is unavailable.

## Commands And Observations

Command:

```text
npm exec -- vitest run src/features/medical-writing/protocol-workbench/DesignElementsCards.test.jsx --environment jsdom
```

Result:

```text
Test Files  1 passed (1)
Tests       3 passed (3)
```

The focused tests exercised:

1. Selecting the second objective sends `primary_objective: 1`.
2. A pending original operation id is recovered after remount; `adoptDesignCard` is never called a second time.
3. A confirmed second objective remains displayed and checked after reload.

## Blockers Or Missing Environment

- No execution-environment blocker for the focused component tests.
- Final browser/rendered acceptance was not performed because this worker is explicitly limited to component verification.
- Contract observation requiring Codex review: `design_adoption.py:_objectives_writer` currently writes the full proposed primary-objective list, while `_check_selections` validates the selected index. This worker did not modify backend behavior. Codex should determine whether the canonical fact intentionally retains all proposed objectives with the selected index represented only by the decision record, or whether backend narrowing is a separate required task.
- The server receipt does not contain the selected objective index. If local storage is cleared after confirmation, the UI correctly reports the historical selection as unknown rather than inferring option 0.

## Rerun Requests Or Next Step

- Codex should inspect the two allowed-file changes and run final integration/rendered acceptance.
- Codex should resolve the backend writer/selected-index semantic question before claiming end-to-end “saved fact equals user choice” acceptance.
- No further worker-side changes requested.
