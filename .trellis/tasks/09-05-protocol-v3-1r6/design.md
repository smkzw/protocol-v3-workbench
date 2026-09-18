# 1R.6 bounded design

Reuse DirectApiAdapter, no second harness or provider SDK. A small stdlib HTTP
client injects its completion/probe functions, request model glm-5.3-flash,
reasoning_effort=max; low/high/max are the provider's actual supported levels.
Primary manufacturer source:
https://huggingface.co/zai-org/GLM-5.3-Flash/blob/main/README.md (Note section).
Official HTTP interface:
https://docs.bigmodel.cn/cn/guide/develop/http/introduction
Installed omp catalog auth/zhipu-coding-plan.kdl pins coding endpoint
https://open.bigmodel.cn/api/coding/paas/v4 (not the metered generic endpoint).

Keep four-role registry schema. Default JSON switches LLM/support only; a separate
explicitly selected DeepSeek profile must require confirmation, no implicit fallback.
Retain OCR/translation declarations unchanged. Public provider identity is
zhipu-coding-plan, direct-api. Observed model comes from HTTP response model,
observed provider is the fixed official transport endpoint identity, not an
invented response field. Requested effort vs unreported server effort stay distinct.

Credential resolver reads current omp SQLite in mode=ro, never instantiates
write-capable AuthStorage. Current login api_key source precedes static entries;
disabled/blocked entries excluded. Deterministic first eligible order matching
fresh no-session omp selection; bind one chosen credential for the call, no
automatic credential/model retry on unknown outcome. Key object repr must not
expose material. No credential material in function result receipts or logs.
Schema incompatibility returns a typed actionable error, no fallback to monitoring.

Ownership: worker client/profile only, Codex credential resolver only.

Clarification from installed omp source review: this is the same stored provider
binding and normal fresh-session ordering, not a full clone of omp credential
selection. peekApiKey/selectCredentialByType can return a blocked fallback, and
getApiKey owns additional ranking/session/env behavior. The product deliberately
does not copy that runtime or attempt blocked credentials/static substitution.
All-blocked is a recoverable configuration outcome, not automatic rotation.
Current actual binding has available login keys; only that case is probed.
Offline synthetic tests first. Codex alone runs one minimal real probe after
independent offline checks; durable pending marker before request, safe receipt
after response, no second request on unknown outcome. No patient/project payload.
