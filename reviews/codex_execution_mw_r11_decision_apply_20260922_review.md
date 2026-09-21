# Codex Execution Review: mw_r11_decision_apply_20260922

## Verdict

ACCEPT after owner revision.

## Worker Outputs

- The declared primary route was `codebuddy/codebuddy-cli/deepseek-v4.1-flash:max`.
- The execution runner did not obtain a usable resumable primary result and used the manifest-declared first fallback: `zcode/zcode/GLM-5.3-Flash:max`, session `sess_858de745-44cd-4934-b788-c22cfafd9776`.
- The fallback worker inspected the inherited implementation, found list-valued StudyDefinition fields and three structured design paths were mishandled, repaired the field shaping, and reported focused checks.
- Guard audit: `audit-execution` returned `ok: true`; the required worker output and stdout receipt are present.

## Codex Independent Verification

- Owner review found a P0 contract break absent from the worker report: v0.4 model output could not carry `fact_path`, so every real decision-card confirmation would fail. The gateway schema, task context, runner validation, and prompt were revised to use an explicit allowlist derived from the existing StudyDefinition adoption contract.
- Owner also restricted the endpoint to exactly one decision per request, preventing partial writes across cards, and replaced the time-based browser idempotency key with a stable job/decision/option key so an unknown network outcome can be retried without duplicating the fact confirmation.
- Backend concentrated verification: `111 passed` across `test_medical_writing_full_draft.py`, `test_ai_gateway.py`, and `test_ai_task_runner.py` using the repository Python 3.12 environment.
- Frontend inventory before the final two-line hardening: 15 Vitest files / 110 tests and 48 Node files / 65 tests passed. Production build after the final hardening: 1971 modules built successfully; only the existing bundle-size warning remains.
- `git diff --check` passed.
- Rendered browser check of the existing v0.3 artifact confirmed legacy candidates remain readable but the adoption action is disabled. A real v0.4 artifact does not yet exist, so rendered decision-card behavior remains part of the next product-model run rather than this code-batch acceptance.
- The current batch is accepted as an engineering implementation. It does not accept any generated medical content and does not authorize automatic adoption.

## Boundary

Acceptance is limited to the decision-card persistence and scoped-regeneration engineering path. Real v0.4 model content, rendered decision-card interaction, medical adequacy, and Word adoption remain pending. Existing live services and unrelated runtime state were not modified.

## Hermes

Hermes workflow evidence is the generated execution context, route manifest, stdout receipt, worker report, successful `audit-execution`, this owner review, and the metrics file. The fallback is recorded as an actual runtime event rather than relabeled as the declared primary route.

## Cleanup Decision

Preserve the route manifest, prompt, stdout receipt, worker report, review, and metrics with the commit. Do not delete runtime or conference history. No additional worker rerun is needed because owner verification found and closed the decisive contract defect.
