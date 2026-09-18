# C03 Independent Review — Source / Persistence / Seed Compiler (2026-09-13)

Reviewer: C03 fresh independent session (route zcode/zcode/GLM-5.3). Owner: Codex (final
integrator; acceptance is the owner's decision). Review-only: no repairs, no task closure,
no recursive agents, no product model calls, no listening services, no OCR/translation,
no native Word automation, no live/monitoring writes, no external source edits, no
commit/archive/cleanup. All writes confined to this reviewer_scratch directory.

## Verdict: **CONDITIONAL PASS** (engineering scope)

All five claims were functionally verified with independently devised checks against the
frozen scope. One evidence-backed finding (F-1, minor-to-moderate) plus two minor
observations; no FAIL-level defect. The single condition is stated under F-1.

## Evidence base

- Frozen snapshot: 267/267 files present, hash-verified against artifact_manifest.json;
  live repo identical to snapshot for all 267 files both before and after this review
  (re-verified at end: zero drift).
- Original source DOCX (read-only):
  `MG-K10-CSU-001_临床研究方案-V1.3-0212-clean-0211.docx`
  SHA-256 `73024713c28382ca8fca7c9338d7151256b2765d78d512876731156a9a504199` — re-hashed,
  matches. No personal/contact content is reproduced in this report.
- Environment: clean `env -i`, `PYTHONDONTWRITEBYTECODE=1`, native Darwin TMPDIR,
  `PYTHONPATH=tests:tests/protocol_v3/integration:tests/protocol_v3:services/api:packages:.`,
  `runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python` (3.12.13), node v22.22.3.
- Logs and harnesses: `reviewer_scratch/claim*.py`, `reviewer_scratch/logs/*.log`.

## Claim 1 — DOCX ordered projection: PASS with finding F-1

Independently re-walked the original ZIP/XML (own code, no docx_parse helpers) and
cross-checked the projection:

- Payload hash binding exact; `content_sha256` equals real file SHA; re-parse
  deterministic; `physical_page_count is None`; `status='parsed_pending_source_review'`;
  object ids and locators unique.
- All 2,608 blocks (incl. nested) resolve to real `w:p`/`w:tbl` XML elements via
  independent path walking (locator → element, 0 unresolved).
- Tables: 22/22 projected with identical locator sets; all 5 nested tables retained
  inside cell projections; gridSpan>1 cells 32/32 match XML; vMerge cells 40/40
  (restart 11, continue 29) match XML; per-table text equality 22/22; document-level
  exact char coverage 86,696 == 86,696 (every `w:t` char appears exactly once at leaf
  level; 0 `w:t` outside `w:p`); `table_text_coverage_pending` 0 on this doc.
- Stories: 16 header/footer/footnotes/endnotes parts enumerated; header role 4 blocks,
  footer 2; footnotes/endnotes parts textless in this doc (0 blocks — correct, they
  contain only separators). No invented page numbers.
- Diagnostics: `visual_objects_pending` (10 drawings/pict present) — visual coverage
  explicitly pending as claimed; no tracked changes in this doc (0 ins/del), so none
  reported; altChunk 0.
- SDT/TOC: the single gallery SDT ("Table of Contents") yields 126 `derived_toc` blocks;
  TOC field recognition (`instrText` regex) verified by frozen unit tests incl.
  field-without-gallery.
- EndNote bibliography: this document has no `EndNote.ReferenceList` sdt tag (its sdt
  tags set is empty), so the capability is not exercised by this file; it is verified by
  the frozen test on CMS-D008 (13 references inside content control), which passed in
  my declared-suite run.

### F-1 (finding, minor-to-moderate): bare-field TOC lists outside the SDT project as `body`

- Evidence: document.xml contains 3 distinct TOC fields — 1 inside the gallery SDT and 2
  outside it (`TOC \h \z \c "Table"` and `TOC \h \z \c "Figure"`, the list-of-tables and
  list-of-figures). Their entry paragraphs at body child indices 124, 125, 128, 129
  (e.g. text beginning “表 1 …” with tab + page number, “图 1 …”) project with
  `role='body'`, not `derived_toc`.
- Cause: `_control_role` is consulted only for `w:sdt` wrappers
  (services/api/app/protocol_workflow/agent1/docx_parse.py:137); a TOC field that is not
  wrapped in an SDT is not distinguished.
- Downstream interaction: `read_seed_candidates` grants `source_support='project_material'`
  when a project_primary quote's unit role is `'body'`
  (services/api/app/protocol_workflow/agent1/research_seed.py:139). A quote from such a
  TOC-entry paragraph can therefore be mechanically labeled project-material support,
  even though the instruction text tells the model that 目录 entries cannot
  independently prove design parameters. Human source review remains pending, and the
  instruction is a mitigation, but the mechanical label does not encode this case.
- Reproduction: parse the MG-K10 file (sha above); inspect blocks with locators
  `word/document.xml/body/124:p`, `…/125:p`, `…/128:p`, `…/129:p`.
- Condition for unconditional PASS: either extend derived-TOC recognition to bare TOC
  fields outside SDT wrappers (e.g., mark paragraphs inside a TOC field range), or
  explicitly accept and document this limitation in the pending source-review workflow.
  Owner decides.

## Claim 2 — SourceIdentityService: PASS

27/27 independent challenges on real SQLite + LocalArtifactStore (all in
logs/claim2_identity_challenges.log):

- Reopen with exact bytes; history = committed events only; replay returns the original
  record identity and preserves the successor as current; exactly 2 events after
  revision + replay.
- Metadata conflicts rejected on ANY historical record with same bytes (role or
  jurisdiction) → `source_metadata_conflict:<field>`, no relabel, no event appended.
- Filesystem staging never selects current: bytes staged directly into the artifact
  store without an event do not appear in `list_current`; genuinely adopting those bytes
  later selects them via the event.
- Genuine SQL failure AFTER staging (non-monkeypatch: rogue event occupies the next
  deterministic `domain_event_id`; `append_events` raises EventSequenceConflictError):
  current unchanged, staging retained, old bytes readable, unrelated logical key still
  adopts. Lock-held failure (BEGIN IMMEDIATE blocked → OperationalError "database is
  locked"): current unchanged, retry clean. This independently reproduces what the
  frozen monkeypatch test simulates.
- Event tamper (body_json edited in SQLite) rejected loudly on next read
  (PayloadHashMismatchError).
- Same bytes: distinct ids/storage keys across projects and across logical keys; both
  keys current; histories isolated per project.
- Whitespace normalization stable ('  ib  ' ≡ 'ib', single event). Whitespace-only key
  raises pydantic ValidationError at contract level (see observation O-2).
- Staging loss (store dir removed): `read_content` fails loudly
  (ArtifactNotFoundError); committed identity/history survives.
- Only committed events select current — never filesystem latest — confirmed from code
  (current derived solely from `_history`) and behaviorally. Identity confirmation is not
  MedicalAdmissionUnit (no such construction anywhere in scope; API returns
  `medical_admission: 'pending'`). The store is an application-boundary dependency;
  nothing in scope exposes it to a model worker; no model calls exist in scope code.

## Claim 3 — Mounted API: PASS

In-process TestClient checks (no listening server), logs/claim3_mounted_api_challenges.log:

- Disabled by default (`protocol_workflow_config_from_env({})` → disabled); disabled
  mount returns False and touches no routes; enabled-without-db fails closed
  (ValueError from `adapter_config`).
- No `<db>.artifacts` directory at mount time; created lazily on the first admitted
  source request as `<full-db-filename>.artifacts/content` + `/manifests`.
- Admission gate: non-admitted project → 404 with the stable Chinese 4-field envelope
  (message/responsible_area/can_retry/next_step); no artifact dir created; gate runs
  before any endpoint/UoW.
- POST upload (real synthetic DOCX): 200 with parse projection,
  `medical_admission: 'pending'`, real content hash echoed; GET list; GET parse by id;
  GET content returns byte-exact original with DOCX media type and attachment header;
  unknown id → 404 Chinese envelope.
- Invalid DOCX variants (not-a-zip, zip-but-not-docx, textless-but-valid): all 400 with
  Chinese message + next_step, nothing adopted (list unchanged). source_role is a
  required enum Form field: invalid value → 422 inside the same Chinese envelope
  (route class), nothing adopted — role/version not fabricated (defaults only for
  version 'unidentified'/jurisdiction 'unspecified', which are explicit form defaults).
- Relabel attempt (same bytes, different role) → 409 Chinese actionable detail, original
  record retained; exact re-upload flagged `replayed: true`.
- Mount registers no global exception handlers; legacy app surface untouched.
- Frontend (`protocolWorkspaceApi.mjs` + `protocolSourceApi.test.mjs`, node --test 3/3):
  FormData POST leaves Content-Type/multipart boundary to the browser (header absent),
  optional fields omitted when falsy, error detail normalized to the four approved
  fields with server message preserved, ids URL-encoded for parse and download URLs.
- Limitation (matches the claim's own statement): no UI exists yet; these are
  client/API-contract checks, not browser acceptance.

## Claim 4 — Sparse seed compiler: PASS

30/30 adversarial challenges (logs/claim4_seed_challenges.log):

- Quote binding is per (source_artifact_id, locator) and substring-exact: wrong source,
  wrong locator, fabricated locator, and spliced/concatenated quotes all rejected
  (`seed_source_quote_not_found`).
- Role semantics: competitor_full_protocol and company_style_only body quotes stay
  `reference_only`; heading-role quotes on project_primary are NOT project_material;
  body and table-cell body quotes on project_primary are `project_material`; mixed
  support degrades to `reference_only`.
- user basis requires verbatim raw in the user brief (unseen or whitespace-only raw
  rejected); recommendation basis allowed without references, labeled
  `ai_recommendation`.
- Structure strict: unknown field keys, non-list candidates, empty candidate lists,
  source-basis without references, extra candidate keys (extra=forbid), confidence
  outside [0,1] all rejected; bounds 0.0/1.0 accepted.
- Proposal semantics: multi-dose candidates retained in full (list and string forms),
  `canonical` null per candidate and `{}` overall, `requires_confirmation` always true,
  confidence labeled `model_estimate_not_medical_admission`, missing fields explicit
  with `needs_information` / all-eight `ready_for_review`, user_brief preserved
  verbatim, sparse empty request legal (8 missing).
- Request build: duplicate source identities and artifact/parse hash mismatches
  rejected; request hash stable (same material+intent → same input_sha256).
- The eight fields are candidate contracts, not intake forms; no canonical/accepted
  state is produced; quote presence is treated as provenance only (entailment remains
  for the human/decision producer) — all as claimed. E0–E3, model normalization,
  admission, recommendations, manuscript, UI/Word remain pending and are not claimed
  as existing.
- Observation O-1 (minor): for `basis='source'` candidates the `raw` field itself is
  not verified against the source (only `references[].quote` is). The claim only
  promises quote verification, so this is an observation, not a defect.

## Claim 5 — Request sizing: PASS

Measured on the real MG-K10 document (logs/claim5_request_sizing.log):

- Payload: 511,934 bytes; 2,586 units (1,258 paragraph + 1,328 table-cell), equal to the
  full leaf-paragraph count — no truncation (no cap exists in the code path; all units
  materialized).
- Unit text union is exactly equal to leaf block text (whitespace-normalized equality)
  — no silent loss or alteration; repeated-row-text removal verified: 0 of 1,328 cell
  units carry the parser-joined row text; each cell carries only its own text; row
  membership is explicit via shared `table_row` plus `cell_index` (273 multi-cell rows);
  ~355,109 characters avoided versus a naive row-repeat-per-cell projection.
- Every unit locator resolves to a real XML element (0 unresolved), so any quote can be
  traced to its exact XML location.
- Request binds source identity, real content hash, role, version, parser version, and
  diagnostics (incl. the document's `visual_objects_pending`); input hash stable.
- No model call is made and no provider-budget claim exists in the code; dispatch
  context admission remains pending, as the claim itself states.

## Minor observations (no action required by this review)

- O-1: `raw` for source-basis candidates unverified (see Claim 4).
- O-2: `SourceIdentityService.adopt` strips `logical_source_key` but does not itself
  reject an empty result; the contract's NonEmptyText raises pydantic ValidationError,
  and the API layer's NonEmptyText Form field rejects whitespace-only input earlier
  with the Chinese envelope. Application-internal callers get a ValidationError rather
  than a graceful ValueError (source_identity.py:99–104).
- O-3: `parse_docx` re-opens the archive (BytesIO) a second time to enumerate story
  parts; single-pass would halve parse work at this size (~0.9 s per parse observed
  across the suite; not a defect).

## Review limitations

- EndNote bibliography handling is not exercised by the MG-K10 document itself (it has
  no EndNote sdt); capability evidence is the frozen CMS-D008 test, which passed in my
  run of the declared suite.
- Concurrency (two service instances) is covered by the frozen test (passed); I did not
  duplicate it.
- Browser/UI acceptance does not exist to perform (no UI), consistent with the claim's
  stated limitation; frontend conclusions are contract-level only.
- Several intermediate harness failures during this review were my own test-expectation
  bugs (documented in the logs); every check gating the verdict passed in its final run
  against the frozen code. Two early FAIL lines in logs/claim3 (D4) and logs/claim5
  (Z3) are harness artifacts superseded by the corrected checks in the same log series.

## Declared test targets (all pass)

- pytest: test_source_identity_product.py (7), integration/test_source_import_api.py (2),
  test_agent1_docx_parse.py (9), test_research_seed_normalization.py (7) — 25 passed in
  0.82 s (logs/pytest_declared_targets.log).
- node --test protocolSourceApi.test.mjs — 3 passed (logs/node_protocolSourceApi.log).

## Summary for owner decision

- CONDITIONAL PASS. The one condition is F-1: bare-field TOC lists outside SDT wrappers
  project as `body`, which can interact with `project_material` support labeling in the
  seed compiler. Either extend recognition or explicitly accept the limitation in the
  pending human source-review gate.
- Everything else in the five claims is verified with independent, reproducible evidence;
  frozen files were not modified (267/267 hash-identical after review).
