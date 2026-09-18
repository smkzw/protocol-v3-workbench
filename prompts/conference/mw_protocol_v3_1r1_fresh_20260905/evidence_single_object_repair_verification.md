Delegated mode. Continue the same bounded conference session for task `mw_protocol_v3_1r1_fresh_20260905`, role `evidence_single_object`.

You are the independent read-only verifier, zcode/zcode/GLM-5.3:max. Resume only your prior verifier session sess_e31a1421-b58b-4d69-8025-7a0795fbc289, never the worker session. Do not reselect routes, start agents, browse, or claim final acceptance. No home instruction discovery. Tools remain enabled for the bounded source/temporary-test review.

Hard boundaries:
- Work in the runner-provided isolated checkout. No live/monitoring/runtime-library/SOP writes, no services, product model/OCR/translation calls, installs, staging, commits or cleanup.
- Product source, tests, fixtures, plans and historical evidence are READ ONLY. You may create an additive repro via apply_patch only under runs/mw_protocol_v3_1r1_fresh_20260905/repair_verification/. Pytest-generated new evidence may use that directory.
- Do not write the runner-managed report path `runs/conference/mw_protocol_v3_1r1_fresh_20260905/evidence_single_object_repair_verification.md`; return the complete report and let the runner persist it.
- Do not read the execution worker's reports, logs, private reasoning or evidence summaries. Use source, original contract, independent probes and your actual tests.

Initial read set:
- `context/mw_protocol_v3_1r1_fresh_20260905_conference_context.md`
- `plans/mw_protocol_v3_review_amendment_20260905.md`
- services/api/app/protocol_workflow/storage/sqlite.py
- services/api/app/protocol_workflow/storage/selected.py
- tests/protocol_v3/test_repository_backends.py
- tests/protocol_v3/test_sqlite_product_storage.py
- runs/mw_protocol_v3_1r1_codex_20260905/test_acceptance_probes.py
- runs/mw_protocol_v3_1r1_codex_20260905/test_projection_atomicity_probes.py
- runs/mw_protocol_v3_1r1_codex_20260905/test_schema_constraint_probe.py

The original context's hashes are historical, not the current review target. The amendment supplies current authorized scope. Frozen current hashes, verify before testing and after review:
- sqlite.py c971cb0057c7adf03ec4d7bddd96d2700454afa16c469ba02c408e763ea5941f
- selected.py 153fc687d1414ca41218daec7b1777a73e98dbf8476491ba926a91c3d9d7a6d3
- test_repository_backends.py 0b1dd33b2b551fb6b144d3df1bff652d886e51edf76b82bff94420d6c1d044f5
- test_sqlite_product_storage.py 411c9c77da86dd8030be25548bdaccc9d04f4ce7162e596c06c0b3a6ef66b5b3

Task:
Independently re-evaluate Task1R.1 after the candidate changed. Your earlier conditional READY was not accepted: executable probes exposed foreign schema adoption, pre-entry autocommit and caught compound-write failure. Later a same-table/same-column CTAS clone exposed missing constraint checks. Decide from current code/tests whether these defects are actually closed; do not repeat your previous answer or merely cite a passing count.

Use original ports/repositories.py and ports/unit_of_work.py plus the actual application/service.py/events/unit_of_work.py callers as criteria. Focus on transaction entry, all mutators, caught event/projection partial SQL failure, nested/closed/rollback semantics; reject memory product paths and naive timestamps; readonly rejection of foreign/malformed schema; full PK/UNIQUE/NOTNULL semantics, owned-schema positive control; no PoC import or startup side effects. Original negative fixtures are immutable. Distinguish current v1 constraints from future schema-version migration requirements (1R.2 may add an allowlist table); do not silently treat latest-schema-only fingerprint as future migration proof. Current owned DDL has no CHECK/FK declarations, so describe introspection limits proportionately instead of inventing unrelated security completion.

Run the three main probe files and focused repository/product tests with PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=services/api:packages:. /opt/homebrew/bin/python3.12 -m pytest ... -q -p no:cacheprovider, then full tests/protocol_v3 if valid. No whole-repository tests or app.main import here. Record actual test commands/counts, current SQLite version, new probes if needed, exact line references and remaining concerns. Avoid duplicate broad exploration; actual source/behavior review is required.

Output schema:
# Conference Output: mw_protocol_v3_1r1_fresh_20260905 - evidence_single_object
## Output
Recommended READY or NOT_READY for Task1R.1 only; concrete residual defects with priority/file/line/reproducer/remedy; resolved versus deferred findings; exact commands/results and before/after four hashes; limitations and source boundary. You do not close the task or assert product/Word/clinical/UI acceptance.
