# Task 1.7 same-session independent acceptance follow-up 3

Resume the same independent acceptance session and re-open the current files.
Your remaining P2 showed that the module-level `_seal_validated_request(**kwargs)`
could sign arbitrary fields.

That callable and the module-level proof key/proof helper have now been removed.
The only proof issuer is the public `build_request` closure, whose first action
is the complete RoleEntry/Skill/artifact/region/session validation path through
`_validated_request_kwargs`; it cannot accept raw dispatch fields. The proof
key exists only inside the controlled closure. The dispatcher receives only a
verify-only predicate. The regression test now confirms neither the request
class factory nor a module-level arbitrary-fields sealer exists, and confirms
post-validation field mutation fails before probe/transport.

Read-only acceptance scope remains the same. Reproduce the latest private
sealer bypass and determine whether any caller-facing API can sign arbitrary
unvalidated dispatch fields without first passing the complete builder checks.
Confirm the prior findings remain closed. You may run deterministic offline
tests only; do not modify files, start services, or invoke live models, OCR,
translation, or medical-monitoring workflows.

Return `READY` or `NOT_READY`, P0-P4 counts, exact evidence, limitations, and
next safe action. READY requires no remaining P0-P4 finding in Task 1.7 scope.
