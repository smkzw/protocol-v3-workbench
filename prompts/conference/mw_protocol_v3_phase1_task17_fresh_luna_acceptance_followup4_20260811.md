# Task 1.7 same-session independent acceptance follow-up 4

Resume the same independent acceptance session and re-open the current files.
The proof/HMAC design has been removed entirely, so there is no signer, key,
proof helper, factory closure, or proof-bearing request.

`build_request()` now retains non-serialized authoritative binding evidence
(NodeExecutionContract, SkillDefinition, RoleEntry, exact artifacts and selected
region). On every dispatch, before gate/preflight/probe/transport, the Harness
reruns the complete Role/Skill/artifact/region/session validation from that
evidence, rebuilds the canonical request fields, and requires exact equality
with the actual payload. Direct construction, copied requests and altered
fields therefore fail closed without relying on hidden capabilities. The
regression now also requires `build_request.__closure__ is None`.

Read-only acceptance scope remains unchanged. Reproduce the former class,
module-helper and closure-signer bypasses; confirm no proof operation exists.
Then test whether a request that did not pass the complete builder validation,
or whose fields/evidence were changed afterward, can reach probe/transport.
Confirm prior findings remain closed. Deterministic offline tests only; do not
modify files, start services, or invoke live models, OCR, translation, or
medical-monitoring workflows.

Return `READY` or `NOT_READY`, P0-P4 counts, exact evidence, limitations and
next safe action. READY requires no remaining P0-P4 finding in Task 1.7 scope.
