# Implementation and ownership

Execution-plus-fresh-review: one worker owns coherent graph/runtime/PoC adapter
and tests, providing context relief; Codex independently integrates and verifies.
No manager declared by live packet. Main does not edit worker files while running.

1. Read accepted graphs/fakes and product ports. Record failing executable tests.
2. Minimal runtime + thin adapter, explicit v1_1 persistence and committed dispatch.
3. Three-case recovery/decision matrix including own-process kill and reopen.
4. Record commands/results, code size, recovery/observability/migration tradeoffs.
5. Codex audit-execution and focused/full regression, then fresh reviewer; worker
   cannot close task. No LangGraph spike needed for this approved typed route.

Retain all prior evidence and seven Task2.1 hashes. Never start services or models.
