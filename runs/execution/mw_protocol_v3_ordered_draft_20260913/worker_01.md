Reading the assigned context and plan, then the V1.3/1.4 structure and existing StructuredTable/ChapterSkillOutput contracts.Pulling V1.3/1.4 product structure, ChapterSkillOutput, and StructuredTable definitions next.Locating StructuredTable and the V1.3/1.4 ordered-chapter sections with a focused worker pass.Implementing red-first: writing the failing tests, then the minimal candidate module.Running the new ordered-draft tests and the structured-table contract tests.Confirming only the two authorized files changed, then emitting the report.# Execution Output: mw_protocol_v3_ordered_draft_20260913 - worker_01

## Boundary And Context Check

- CWD bound to authorized workspace; edits limited to the two assigned new files.
- Read: execution context/plan; `plans/mw_protocol_v3_implementation_plan_v3_20260912.md` §V1.3/1.4章节产物结构细化; `plans/mw_protocol_v3_design_v1.4_20260912.md` §§4–6; `services/api/app/protocol_workflow/registries/chapters.py` (`ChapterSkillOutput`/`ContentObject`); `packages/contracts/workbench_contracts/models.py` `StructuredTable` (+ cells/notes validators); `protocol_v3.SemanticBlock` (text-only confirmed blocks — not reused as candidate carrier).
- Did not modify Plan/checkpoint/old tests/schemas/frontend/runtime, did not commit/clean/archive, did not start services/browser/model/OCR/translation, did not run `cleanup-execution`.
- Agent/provider/model identity for this pass: **未报告** (orchestration label `pi`/`cursor`/`default` is not treated as a concrete model id).

## Work Performed

Red-first then minimal implementation:

1. **`tests/protocol_v3/test_ordered_chapter_draft.py`** — anti-examples then positive JSON round-trip.
2. **`services/api/app/protocol_workflow/registries/ordered_draft.py`** — candidate-only ordered blocks reusing `StructuredTable` by type.

Behavior delivered:

- Ordered blocks: paragraph / table (discriminator `kind`).
- `OrderedDraftTableBlock.table: StructuredTable` — no copied table type; StructuredTable validators retained.
- Unique `block_id`; unique `table_id`; enclosing `block_id` must equal `table.block_id`.
- `evidence_refs ⊆ known_evidence_ids` only (ID-in-universe; **not** medical authenticity).
- `refuse_occurrences_as_instances()` fails closed on `ContentObject.occurrences` expansion.
- No `medical_admission` / `quality_score` fields generated.
- Input `StructuredTable` detached via dump→validate; nested table remains mutable `WorkbenchModel` (no deep-immutability claim).
- Legacy `ChapterSkillOutput` untouched.

Subsequent interface suggestion (docstring only, not implemented): optional ordered-blocks envelope beside legacy grouped `ChapterSkillOutput` for V1 wiring; adoption into `SemanticDocumentRevision` stays a separate confirm step with real bindings.

## Artifacts And Evidence

| Path | Role |
|---|---|
| `services/api/app/protocol_workflow/registries/ordered_draft.py` | New candidate module |
| `tests/protocol_v3/test_ordered_chapter_draft.py` | New red-first tests |

Git scope of this worker: only those two paths as `??`. Other dirty tree files were pre-existing and untouched.

## Commands And Observations

```text
env -i HOME=... PATH=... \
  PYTHONPATH=services/api:.:tests:tests/protocol_v3:tests/protocol_v3/integration \
  runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python -m pytest \
  tests/protocol_v3/test_ordered_chapter_draft.py \
  tests/test_structured_table_contracts.py -q --tb=short
```

Observation: **14 passed in 0.36s** (8 new ordered-draft + 6 existing structured-table contract).

Covered: duplicate block_id reject; table identity mismatch reject; dangling evidence_ref reject; occurrences-as-instances reject; 段落A→2×2表1→段落B→同kind表2 JSON round-trip (order, ids, cells, notes/sources); input mutation isolation; no admission/score minting; nested StructuredTable mutability honesty.

## Blockers Or Missing Environment

None for this bounded item. Venv and PYTHONPATH as specified worked.

## Rerun Requests Or Next Step

Codex review/acceptance of the two new files. Suggested follow-ups (out of this worker scope):

1. Wire optional ordered candidate emission beside legacy `ChapterSkillOutput` without breaking fixtures/checkers.
2. Separate confirm path: map ordered candidate → `SemanticDocumentRevision` with real fact/evidence/admission IDs (do not auto-mint).
3. Decide whether table-cell `provenance_lineage` should also be validated against `known_evidence_ids` (currently only block-level `evidence_refs`).
