# Same-session bounded batch1 repair

Resume sess_b91d51c2-ce9c-48fe-9add-59201fcf8927 after terminal worker report.
Original task context and allowed-source boundaries remain. This is an explicit
EDIT round, not final acceptance. No services, product calls, web, external writes,
credential reads or other agents. Do not alter runner-managed report/log files.

Read original context, the24authored contract/skill JSONs, batch1 fixtures and
test_chapter_batch1.py. Additional read-only inputs:
- reviews/mw_protocol_v3_3r3_diagram_reference_check_20260906.md
- reviews/mw_protocol_v3_3r3_batch1_content_spec_20260906.md
- runs/mw_protocol_v3_3r3_batch1_20260906/test_codex_batch_content.py
- runs/mw_protocol_v3_3r3_batch1_20260906/test_codex_batch_assembly.py
- services/api/app/medical_writing_protocol_template.py relevant existing fact bindings

Codex independently read all24authored files. Existing8tests pass with proper
TMPDIR. Six independent content counterexamples FAIL (codex_content_red_20260908.xml):
1.no external service party still requires three tables/service cells;
2.single-arm nonrandomized diagram still requires allocation ratio;
3.cover and summary fail binding existing framing.protocol_id;
4.diagram supporting asset identity/hash absent;
5.drug registration classification is incorrectly used as eligibility registry path;
6.glossary requires only headers, not any actual entry cells.

Fix these root causes across contracts/skills/fixtures without weakening actual
applicable obligations. Scoped writes: the original twelve contract and twelve
skill files; tests/fixtures/protocol_v3/chapter_content_v2/batch1.json;
tests/protocol_v3/test_chapter_batch1.py; NEW diagnostics under
runs/mw_protocol_v3_3r3_batch1_repair_20260908/. Do NOT edit the core/schema,
assembly helper, Codex counterexample tests, plans/checkpoints or later batches.
Codex already repaired assembly separately: selected coverage_roles controls the
input slice, missing selected files error, CLI validation errors return2. Its
11checks pass. Treat assembly as read-only.

Required repairs:
- Unconditional contacts require sponsor/investigator only; actual service parties
  remain conditional with explicit role/address obligations. Use existing
  conditional-required fact paths and project-specific QC, not phantom N/A cells.
  Preserve positive service-party fixture plus no-service positive; keep old
  missing-role/address counterexamples effective for applicable parties.
- Allocation ratio is conditional on actual randomization. Require its fact when
  active and retain single-arm positive. Diagram omission for suitable simple
  studies has a documented applicability disposition per source246; do not silently
  discard the default diagram recommendation. Do not edit core to implement the
  future conditional executor; record those semantic checks as deferred.
- Reuse framing.protocol_id, framing.document_title, framing.version,
  framing.study_phase where applicable (original source-spec requirement).
  No separate editable synopsis.protocol_id/document_control.protocol_id. Reuse
  known picos paths from existing bindings for other shared clinical values,
  and explicitly state new metadata/derived values' ownership. Version/date must
  not be an unstructured string that silently loses the independent version.
- Registration classification is drug application classification, not proof of
  a clinicaltrials.gov/Chinese registration. Source summary table242 has17rows:
  ID,title,version/date,phase,registration classification,sponsor,PI,sites,
  objectives/estimands/endpoints,design,population,drug,interventions,N,statistics,
  overall trial duration,participant visit duration. Preserve all17row selectors
  (currently only5requiredcells), distinguish body facts from projected table cells.
  Actual registry consistency belongs to applicable registered eligibility, not
  classification. No invented registered record.
- Glossary must require actual abbreviation/expansion/Chinese-meaning entry
  content for used terms, not only headers. Add empty-entry negative while
  retaining existing four fixture families. No invented real medical validation.
- Bind actual SVG supporting asset/hash from Codex check, example-only. Prevent
  source example1:1/IWRS/12week/placebo being automatic project facts; model all
  applicable arms' exit transitions. No claim native SVG/Word rendered acceptance.
- Separate independently required source-floor claim groups (current group with
  several claim types accepts ANY one). Cover identity/confidentiality, summary
  objective/estimand, diagram content/transition each need applicable evidence.
- Remove stray 受试者 in newly authored SOA CtQ wording; use 试验参与者.

Existing tests contain batch-stage assumptions: global directory exactly12 and
fixed unconditional service cells. They may be corrected with explicit replacement
coverage: selected batch remains exactly12, all applicable cells remain required,
no-service scenario valid, later batch files don't invalidate batch1. Add source
obligation assertions, never delete a negative fixture or hide a failure. Existing
48fixtures remain (values/schema bindings may change with corrected contracts);
additional focused applicable/inapplicable negatives/positives allowed. Update
count assertion to verify original48IDs preserved plus explicit new fixtures.

Use existing venv and sanitized env including TMPDIR from original Codex run:
/var/folders/yb/31r9763x6_54mdxswxk36c4w0000gn/T/ . Target original8tests plus
both Codex files. Do not rerun unrelated entire legacy suite or install anything.
Report exact fixes/test evidence, current counts, deferred obligations and any
unresolved defect. Return compact report for runner; do not close the task.
