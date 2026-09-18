# 1R.2 implementation

Execution choice: bounded execution plus fresh verification for product mounting
and storage integration. Main owns management/test environment; one governed
worker owns code. No simultaneous file ownership and no extra manager by default.

1. Inspect router/application/storage interfaces, main composition and H6 tools.
2. Resolve isolated legacy test dependencies with version receipt; sanitize
   child runtime paths before real imports. PyMuPDF personal usage is approved.
3. Write red tests: actual mounting default-off, allowlist/restart, non-admitted
   projects, legacy validation and no added worker/old DB side effects.
4. Minimal composition, allowlist migration and real-main include_router.
5. Focused green, adjacent contracts, protocol_v3 and full repository regression
   using existing scope/runtime guards. No product models or real external jobs.
6. Fresh verifier checks changed source and evidence, freeze hashes and only then
   close task without archive. Next task 1R.3, not premature 1R.4.

Allowed code: narrow services/api/app/main.py wiring, protocol_workflow/api/
composition/router and storage/sqlite.py versioned allowlist, relevant new
tests/protocol_v3 tests and isolated test setup. Declare impact before expansion.
No monitoring, legacy business logic, negative fixtures, product model config,
immutable Plan or historical evidence changes.

New evidence: runs/mw_protocol_v3_1r2_20260905/.
Prerequisite: reviews/codex_mw_protocol_v3_1r1_storage_gate_20260905.md.

User amendment: old no-main-mount and schema-v1 assertions are explicitly
superseded by this task. Update them to the approved current functionality.
No new security engineering/tests or security-specific acceptance stage.
Scientific and actual functional correctness remain required; security exclusion
is recorded as excluded work, not a successful test or completed implementation.
