# Conference Context: mw_protocol_v3_phase1_task110_acceptance_20260812

Created: 2026-08-12 03:50:45
Objective: 独立验收 Task 1.10 v2→v3 dry-run migration、quarantine、幂等 lineage 与单向 cutover/旧 mutation guard；禁止安全测试和任何写入
Task type: `high_risk_contradiction_review`
Risk: `high`
Conference mode: `parallel`

## Codex Main Venue

- Chair: Codex.
- Duties: understand the real task, decompose, define sources of truth, route work, protect boundaries, verify final artifacts, own visual/browser/PPT/PDF checks, own production writes, and deliver to the user.

## Conference Panel Assignment

    - Visual/design/HTML/PPT tasks use a Codex-led panel with no sub-venue chair: Pi/Oh My Pi `kimi-code/k3-256k` (high). If unavailable, the runner tries Grok Build `grok-4.5`, then the distinct Cursor `cursor-grok-4.5-high` route, then the distinct Pi/OpenCode Go `gpt-5.6-luna` (max) route. The Codex subAgent Luna route remains a separate native/CLI compatibility path.
- Chinese labels or Chinese sentence review is handled directly by Codex and does not start a conference.
    - Other complex tasks use a Codex-chaired panel with no sub-venue chair. Participant 1 is Pi/Alibaba `qwen3.8-max` (xhigh) during the Beijing 22:00-07:00 window. Outside that window its exact Qwen Max node is replaced by Pi/OpenCode Go `deepseek-v4-flash` (max); during the night window, every exact Pi/cms-smk `deepseek-v4-flash` node is replaced by the same Pi/OpenCode Go route. Its remaining fallbacks are Pi/cms-smk `deepseek-v4-flash` (max), Pi/OpenCode Go `deepseek-v4-flash` (max), and Pi/DeepSeek `deepseek-v4-flash` (max), with effective-route deduplication. Participant 2 is Grok Build `grok-4.5`, with the distinct Cursor `cursor-grok-4.5-high` and Pi/cms-router `minimax-m3` as fallbacks. Codex remains the final authority. The explicit Luna native/CLI compatibility route remains available for execution roles that declare Codex subAgent.
- Every conference role starts with one bounded same-session pass. Codex reviews its quality and may dispatch zero or more targeted follow-up prompts through the same session. A new session is a routing failure unless a primary role failed before a resumable session existed and the documented fallback was activated.

## Source Of Truth

- Frozen plan `.hermes/plans/2026-08-09_020923-mw-protocol-multi-agent-rearchitecture.md`, Task 1.10. Verify its SHA-256 independently; do not accept a supplied hash as proof.
- Task contract `context/mw_protocol_v3_phase1_task110_20260812_context.md` for scope, authority and acceptance criteria only. Do not read execution/worker/manager/conference-peer reports.
- Actual implementation under `services/api/app/protocol_workflow/legacy/`, `config/medical_writing/protocol_v3/v2_v3_mapping.json`, and the four `tests/protocol_v3/test_{v2_v3_migration_dry_run,v2_v3_migration_idempotency,legacy_read_parity,legacy_mutation_guard}.py` files.
- Read-only current v2 contract evidence named by the mapping spec and mutation inventory, plus `services/api/app/main.py` and `services/api/app/source_intake.py`. These are evidence only and must not be edited or imported in a way that starts services or opens runtime databases.
- Current filesystem and independently executed tests outrank all prose claims. No live database, company-corpus asset, service or external network source is an input.

## Scope

- In scope: read-only acceptance of seven-family inventory/quarantine accounting, real-contract mapping and whole-payload preservation, deterministic 3,878-row synthetic denominator, idempotent/revision lineage, exact read parity, forward-only project cutover, deterministic route/service mutation inventory and two-layer functional fail-closed behavior.
- In scope: run the four focused tests, full `tests/protocol_v3/`, API-isolation selector and bounded counterexample probes. Check plan hash, mapping/inventory hashes, project isolation, source immutability, no silent drop, no lineage overwrite, and the investigator-brochure route/service bypass.
- Out of scope: all security testing, prompt-injection/SSRF/path/access-control testing, live/runtime DB reads or writes, service startup, route mounting, browser/visual work, external research, AI/OCR/translation, Task 1.11 and later phases.
- Out of scope: any file modification. Participants are veto/review only; they must not repair artifacts or write sibling files.

## Success Criteria

- Return exactly one verdict: `READY` only if every material criterion is independently grounded, otherwise `NOT_READY` with a reproducible defect and smallest owning repair scope.
- Seven source families remain explicit; source_count/mapped/unmapped/quarantine accounting is exact and no unsupported record receives a fabricated semantic node.
- Mapping spec binds real model/table/snapshot fields, project/source identity and revision; every source field is explicitly covered/preserved or quarantined; mutation attempts cannot drift hashes.
- Identical key+revision is idempotent; conflicting same revision never overwrites lineage; changed revision creates a retained child relation.
- Cutover is exactly LEGACY_ACTIVE→SHADOW_READ_ONLY→NEW_CANONICAL, with skip/reverse/unknown reuse rejected; reads preserve exact payload/hash/project; unknown/unclassified mutations fail closed.
- Every actual project-bound state-changing old `/medical-writing` route is `legacy_write`; read-only previews are justified. The investigator-brochure route and `SourceRegistryService.register_medical_writing_document` are blocked at route/service layers in both read-only states, while medical-monitoring source intake remains outside this cutover.
- The four focused tests, full Protocol v3 suite and API isolation all pass with zero unexpected skip/error; frozen plan hash and protected-path status remain unchanged.
- Synthetic evidence is not represented as a live migration or production cutover. Standalone contracts are not represented as runtime wiring.

## Parallel Work Rule

For logic-heavy, rigor-sensitive, or artifact-heavy tasks, each participant independently runs the whole bounded workflow and writes a separate output. Leads compare after all available participant outputs are in or explicitly marked pending.

## Timeout Policy

- Participant soft wait: 60 minutes.
- Large-task participant wait: 120 minutes.
- Chair hard wait: 120 minutes.
- Failure rule: Do not fail a model for slow response alone; fail only on terminal error, provider exhaustion/rate limit after controlled retry, empty/truncated retry output, or no useful progress after the high-budget same-session recovery loop. A catalog/auth/transport health preflight timeout or malformed response is diagnostic and must still allow one live route attempt; only a missing CLI or an explicitly invalid, retired, or unlisted model may block before live dispatch. If a resumable session exists after a step/size boundary, continue it before fallback; repeated identical output/tool evidence triggers the no-progress breaker.
- Pass/turn boundary: one conference prompt is one conference pass. The
  `--max-turns` value controls internal Agent tool-calling turns and is never
  set to 1 for substantive conference execution; generated participant and
  chair commands use the route budgets recorded by the guard.

## Risk Boundaries

- External Agents are advisory; Codex remains final authority.
- Codex owns visual/browser/PPT/PDF/rendered checks, live authority checks, final clinical/regulatory conclusions, and production writes.
- Do not mark a slow model failed solely due to latency.
- No security test is permitted. Functional project isolation and mutation/cutover behavior are acceptance contracts, not a security review.
- Do not read any participant, worker or manager report; verifier isolation is mandatory.
- Do not edit any file. Commands must be read-only and must not start services or access live/runtime data.

## Loop Log

- 2026-08-12 03:50:45: Conference initialized by `hermes_workflow_guard.py init-conference`.
