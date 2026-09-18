# 3R.2 acceptance — additive chapter contract schema

Codex accepts the schema task after independent review and repairs. This is not
generated protocol, frontend, native Word, clinical or regulatory acceptance.

## Version-bound evidence

- protocol_v3.py SHA256 b76a048ff1f50cb89ea0504819281e7ef0d0f6f481c73496d577b2cb7ba0f2e9
- test_chapter_contract_schema.py SHA256 bd6a7567a9ccc13b22522ef4b6f9cfc1d14f800e58d30f044136c3e4b9d18524
- Codex positive-obligation tests SHA256 2b74f64f86d11d4fd3bf18e1e27a34b79f54268d625d9dca58c4271a2297e989
- Initial Codex focused run222passed0.60s. Five then seven red counterexamples
  reproduced missing positive obligations, unbound chapter content, undeclared
  repair ownership and absent typed cell requirements. Repairs229passed0.61s;
  final schema+Codex probes23passed0.32s. XMLs remain in the task runs directory.
- Expanded regression1745passed1warning49.30s, codex_expanded_regression.xml:
  tests/protocol_v3, orchestrator PoC tests and Codex2R1/3R1/3R2 probes. This is not
  full-repository coverage; it excludes historical legacy failures and frontend.
- Three v1 captures are byte-identical, including JSON schemas, serialization and
  legacy/compact hashes. Existing v1 classes and expected values remain untouched.

## Lineage and disposition

Worker packet mw_protocol_v3_3r2_contracts_20260906, ZCode GLM-5.3-Flash:max,
session sess_a202ef61-4815-494d-8985-bdf04d60e0bb,1442.593s, terminal/no fallback.
audit-execution PASS. Codex performed bounded repair after the worker ended.

Independent packet mw_protocol_v3_3r2_fresh_20260906, Pi/opencode-go/
muse-spark-1.3-contributor:xhigh, session01a072d8-b019-7000-a308-9aa79b0a6d5f.
Round1REVISE; same-session round2ACCEPT,231tests independently checked. Both exact
output/receipt pairs passed live guard audit_runner_receipt with []errors against
the packet off_peak route. No pending runner or manager, no fallback/redispatch.

Permissions/prohibitions do not count as required content. ChapterV2 now embeds
identity-matched SubstantiveContentContractV2; dependency IDs require repair
ownership. Control content retains template provenance without invented medical
claims. Stable object-cell references are expressible, not proof of rendered cells.

## Direct continuation

3R.3 must emit embedded contracts and jointly lint vocabulary, conditional
required/forbidden contradictions, CtQ references, dependency targets, source
evidence and fixture content. See mw_protocol_v3_3r3_source_preparation_20260906.md.
Schema positivity is not clinical content QC. No casefold rewrite of OOXML style
IDs, no fake patient decision approval in reusable templates. No stage pause.

Parallel legacy frontend findings remain pending6R in
mw_protocol_v3_frontend_readonly_findings_20260906.md, including the reproduced
StrictMode intake defect. No frontend product changes or live service calls made.
