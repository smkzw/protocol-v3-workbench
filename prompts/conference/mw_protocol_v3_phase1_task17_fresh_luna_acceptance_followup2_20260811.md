# Task 1.7 same-session independent acceptance follow-up 2

You are resuming the same independent acceptance session after reporting one
remaining P2: caller-reachable `HarnessDispatchRequest._validated_construct`
could stamp a forged request.

Re-open the current filesystem; do not rely on the prior snapshot. The product
code has now replaced that boolean/private-classmethod convention with a
process-local, canonical-payload-bound HMAC proof. The public request class no
longer exposes `_validated_construct`; `build_request()` seals the validated
request, and `HarnessDispatcher.dispatch()` recomputes the proof before gate,
preflight, probe, or transport. A regression test mutates `allowed_tools` on an
otherwise valid request and requires `request_unvalidated`, zero probe, and
zero transport. Session recovery polarity retains its specific stable error.

Read-only acceptance scope:

- `services/api/app/protocol_workflow/runtime/harness.py`
- `services/api/app/protocol_workflow/registries/loader.py`
- `services/api/app/protocol_workflow/runtime/adapters/`
- `tests/protocol_v3/test_harness_policy.py`
- `tests/protocol_v3/test_registry_loading.py`

Reproduce the former `_validated_construct` bypass and confirm it is closed.
Also confirm the eight earlier findings remain closed. You may run deterministic
offline tests only. Do not write or modify workspace files, start services, or
invoke live models, OCR, translation, or medical-monitoring workflows.

Return a concise independent verdict `READY` or `NOT_READY`, P0-P4 counts,
exact evidence, environment-only limitations, and the next safe action. READY
requires no remaining P0-P4 finding in Task 1.7 scope.
