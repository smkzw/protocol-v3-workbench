# 3R.4 dependency preparation — read-only findings, not implementation

While batch1 worker owns its new files, Codex read inherited Task3.4, current
v2 contract dependency fields, document reducer projection/fact-proposal paths,
API router entry points and application service method inventory. No product
file edited and no graph/QC completion claimed.

## Keep three relationships distinct

1. Fact membership: SemanticDocumentReducer already checks exact fact keys and
   StudyDefinition revision/hash. This proves binding, not medical adequacy.
2. Scheduling: Task3.4 admits only hard/order edges into the DAG. Existing
   ChapterContractV2 has dependency IDs plus repair ownership; it has no typed
   edge-kind field. Add a small explicit registry-level edge representation
   when implementing3R.4; do not infer all cross-references are scheduling edges.
3. Consistency/impact: reciprocal clinical relationships (summary/body, SOA/
   assessments, endpoint/estimand/statistics) must be evaluated without creating
   artificial scheduling cycles. A graph rendering is a projection, not a new
   authority. Preserve the complete affected set on high-fan-out changes.

## Integration obligations

- Current document reducer returns a FactProposal for fact-touching edits;
  its docstring describes adoption then impact then reprojection. The current
  application service methods are study creation/adoption and queries, not an
  implemented document-edit impact pipeline. Router likewise exposes no editor
  command. This is unfinished planned integration, not evidence that the path
  already works end-to-end.
- Carry actual contract IDs and repair owners from final3R.3 registry; resolve
  conditional fact dependencies, including those not unconditionally required.
- Do not make a generated summary a second editable fact store or let a cycle
  workaround erase a clinical consistency link. Project-confirmation invalidation
  needs the changed material facts, not a blanket reopen-all decision.
- Deterministic future tests: hard cycle rejected; reciprocal consistency links
  legal; missing owner/unknown edge identified; unrelated chapters remain stable;
  broad dose/endpoint changes return every affected chapter without truncation;
  same fact update has a single adoption effect under the existing CAS ledger.

These are engineering requirements from current Plan/source inspection, not
new clinical assertions. Serial task order remains3R.3 then3R.4, not parallel
edits to incomplete registries. No product model call or service was started.
