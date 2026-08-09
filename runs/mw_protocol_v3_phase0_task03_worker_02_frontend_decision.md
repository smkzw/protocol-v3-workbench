# Protocol v3 Phase 0 Task 0.3 — worker_02 frontend decision record

Date: 2026-08-09
Task: `mw_protocol_v3_phase0_task03_20260809_111313`
Role: `worker_02`
Execution identity: Codex fallback `codex` / `gpt-5.6-luna`; the requested
`cms-smk` / `cms-model` provider was unavailable before a resumable session.

## Boundary and sources

Work was limited to the isolated Git worktree
`protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/`. The sibling
live `workbench/` remained read-only. No `pnpm-lock.yaml`,
`pnpm-workspace.yaml`, medical-monitoring source/test file, service, runtime,
database, or runner-owned report was edited.

Read before implementation:

- `AGENTS.md` and `frontend/AGENTS.md` in the isolated worktree;
- parent execution context `../context/mw_protocol_v3_phase0_task03_20260809_111313_execution_context.md`;
- parent task context `../context/mw_protocol_v3_phase0_20260809_111313_context.md`;
- `plans/codex_execution_mw_protocol_v3_phase0_task03_20260809_111313.md`;
- `prompts/mw_protocol_v3_phase0_20260809_111313_task03_execution.md`;
- `.hermes/plans/2026-08-09_020923-mw-protocol-multi-agent-rearchitecture.md`, Task 0.3/H4–H6;
- `runs/mw_protocol_v3_phase0_task02_acceptance.md`.

The two prompt-listed context/run files absent from the isolated root were
resolved to the parent `implementation/context` and isolated `runs` copies;
this path mismatch is retained for the manager/Codex handoff.

## Decision and implementation

The frontend package-manager decision is npm with `package-lock.json` as the
intended sole lock. `frontend/package.json` now declares exact direct pins,
`packageManager: npm@10.9.8`, and exact Node/npm engines. The intended test
dependencies are Vitest `4.1.10`, jsdom `30.0.1`,
`@testing-library/react` `16.3.2`, and `@testing-library/dom` `10.4.1`.

The inventory contract is implemented in
`frontend/tests/protocol_v3_test_inventory.mjs`:

- recursively scans frontend test candidates while excluding generated/cache
  directories;
- maps `.test.jsx` only to Vitest/jsdom and `.test.mjs` only to direct
  `node --test`;
- rejects unsupported test suffixes, duplicate paths, wrong runners, unknown
  collected paths, and uncollected discovered paths;
- exposes `--check`, `--json`, `--paths`, and `--run <vitest|node|all>`;
- dispatches exact discovered paths rather than allowing implicit test
  collection.

Focused contract coverage is in
`frontend/tests/protocol_v3_test_inventory.test.mjs`.

## Evidence

- Inventory: 47 discovered files = 3 Vitest/jsdom `.test.jsx` + 44 direct
  Node `.test.mjs`; duplicates/unknown runners/uncollected tests: none.
- Focused inventory tests: 3/3 passed.
- Direct Node runner: 44 files, 48 subtests passed, exit 0.
- `npm run test:inventory`: passed, exit 0.
- `node --check` passed for both inventory files.
- `frontend/pnpm-lock.yaml` SHA-256 before/after:
  `3f101b4e9c833a5154af12f250644cfe60ada682d351c9f028484159d038fba8`.
- `frontend/pnpm-workspace.yaml` SHA-256 before/after:
  `d6d0c24446d91ef762d37c6ba801bb516e65d7055aa9f8027fcd457409a97ce1`.

## Blocker and disposition

`frontend/package-lock.json` was not regenerated. The isolated worktree has no
`node_modules`, and registry access is unavailable in this execution sandbox:

1. `npm install --package-lock-only --ignore-scripts --audit=false --fund=false`
   produced no output for about two minutes and was stopped with SIGINT; the
   lock remained byte-identical.
2. `npm ping` against the configured
   `https://registry.npmmirror.com` failed with `EPERM` while connecting to the
   unavailable local proxy `127.0.0.1:7897`.
3. Direct `registry.npmjs.org` access with proxy variables removed failed with
   DNS `ENOTFOUND`.
4. `npm install --package-lock-only --offline ...` failed immediately with
   `ENOTCACHED` for `@testing-library/dom`.

Because the lock is still the pre-change lock, `npm ci`/clean install, Vitest,
and clean Vite build were not claimed. The current package manifest is
intentionally ahead of the mechanical lock and must not be accepted as H4
until lock regeneration and a fresh install succeed. H5 has only a source-level
inventory plus direct Node evidence here; H6 is not decided by this worker.

## Next safe action

With a working npm registry route, run from `frontend/`:

```text
npm install --package-lock-only --ignore-scripts --audit=false --fund=false
npm ci --ignore-scripts --audit=false --fund=false
npm run test:unit
npm run build
```

Repeat `npm ci`, `npm run test:unit`, and `npm run build` in a second fresh
frontend directory, compare package/lock hashes, then have the execution
manager/Codex review the resulting diff and H4–H6 evidence. Do not modify or
quarantine the pnpm files in this worker.
