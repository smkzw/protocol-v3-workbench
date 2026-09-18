# Design boundary

One typed runtime behind OrchestratorPort, no orchestration framework dependency.
Reuse existing SQLite UoW/events/artifacts/committed-reservation interfaces; avoid
new persistence platform or parallel ad-hoc database. Graph state carries small
identities and references; clinical truth remains in typed application artifacts.
PoC converts old accepted graph nodes to product-owned types, never reverse-imports.
Deterministic injected services stand in for models, QC and calculation; do not
pretend a fake numeric sample-size result is clinical validation. Production
v1_1 execution contracts explicitly bind dependencies; preserve old graph hashes.

Reservation ownership precedes physical synthetic dispatch. After a crash use
existing recorded outcome; missing receipt means unknown, not automatic retry.
Human decisions and final semantic application require stable idempotency/CAS.
Actual SQLite process-death tests prove durable behavior; memory only for comparison.
Worker selects minimal concrete types after reading ports; missing capabilities
outside allowed new files must be reported, not silently patched.
