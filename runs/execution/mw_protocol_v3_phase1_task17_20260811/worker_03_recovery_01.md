All repair work complete. Here is the full execution report.

---

# Execution Output: mw_protocol_v3_phase1_task17_20260811 - worker_03_recovery_01

## Boundary And Context Check

**Initial read set consumed:**
- `AGENTS.md` — operating principles
- `context/mw_protocol_v3_phase1_task17_20260811_context.md` — parent Task 1.7 scope and boundaries
- `services/api/app/protocol_workflow/runtime/adapters/codex_app.py` — my owned file (pre-repair)
- `services/api/app/protocol_workflow/runtime/adapters/omp_cli.py` — my owned file (pre-repair)
- `tests/protocol_v3/test_harness_policy.py` — my owned test file (pre-repair)

**Authoritative CLI evidence re-read directly (required by repair contract):**
- `codex exec --help` (bundled executable at `/Applications/ChatGPT.app/Contents/Resources/codex`): confirmed `--json` (not `--jsonl`), `--output-schema <FILE>`, `--model`. No `--resume` flag on `exec`.
- `codex exec resume --help`: confirmed `codex exec resume [OPTIONS] [SESSION_ID] [PROMPT]` subcommand; supports `--model`, `--output-schema`, `--json`.
- `omp --help` (local executable at `/Users/smkzw/.local/bin/omp`, v17.2.9): confirmed `-p, --print` (non-interactive), `--auto-approve` (auto tool approval), `--thinking=<value>` accepts `off, minimal, low, medium, high, xhigh, max, auto` (`on` absent), `--max-time=<value>`, `-r, --resume=<value>`, `--provider`, `--model`, `--no-tools`.

**Additional dependent files read:**
- `packages/contracts/workbench_contracts/protocol_v3.py:858-896` — confirmed `NodeExecutionContract.provider_session_id: Optional[NonEmptyText] = None` (the correct session source; distinct from `idempotency_key`)
- `services/api/app/protocol_workflow/runtime/harness.py:202-260, 521-595, 655-728` — confirmed `HarnessDispatchRequest` does NOT carry `provider_session_id`; `build_request` does not map it; `HarnessDispatcher.dispatch()` calls `adapter.dispatch(request)` at line 708 without forwarding a session id

**Boundary compliance:**
- Wrote only authorized files: `codex_app.py`, `omp_cli.py`, additively edited `adapters/__init__.py` (docstring only) and `tests/protocol_v3/test_harness_policy.py` (CLI portions only).
- No canonical contract, registry, shared gate, frontend, legacy, medical-monitoring, or production path modified.
- No live model/CLI/service calls — only `--help` reads for evidence.
- Medical-monitoring diff: **0**.

## Work Performed

### Defect 1+2 repaired: `codex_app.py` — `--json` flag and `exec resume` subcommand
- `_JSONL_FLAG = "--jsonl"` replaced with `_JSON_FLAG = "--json"` (confirmed by `codex exec --help`).
- Removed `_RESUME_FLAG`. Added `_RESUME_SUBCOMMAND = "resume"`.
- `build_codex_exec_plan()` now builds two closed plan shapes:
  - New dispatch: `['exec', '--model', M, '--json', '--output-schema', S]`
  - Resumed dispatch: `['exec', 'resume', SESSION_ID, '--model', M, '--json', '--output-schema', S]`
- Both shapes use `--json`, `--output-schema`, explicit model, tools enabled, no `--max-turns 1`.

### Defect 3+4 repaired: `omp_cli.py` — `-p`/`--auto-approve` and exact thinking values
- `_YES_FLAG = "--yes"` replaced with `_PRINT_FLAG = "-p"` and `_AUTO_APPROVE_FLAG = "--auto-approve"`.
- `_THINKING_ON_EFFORTS` frozenset replaced with `_EFFORT_TO_THINKING` mapping: `none`→`off`, `low`→`low`, `medium`→`medium`, `high`→`high`, `xhigh`→`xhigh`, `max`→`max`. Added `_SUPPORTED_THINKING` frozenset mirroring the exact CLI accepted set.
- `_resolve_thinking_value()` raises `ValueError` on unsupported effort values.
- `--thinking on` is never generated (`on` not in accepted set).

### Defect 5 repaired: both adapters — explicit nullable session_id
- `build_codex_exec_plan()` and `build_omp_cli_plan()` already took `session_id: str | None`; the adapters no longer substitute `idempotency_key`.
- `CodexAppAdapter.build_command_plan()` and `.dispatch()` now accept `*, session_id: str | None = None` as an explicit keyword parameter.
- `OmpCliAdapter.build_command_plan()` and `.dispatch()` now accept `*, session_id: str | None = None`.
- The adapters never read `request.idempotency_key` for session/resume purposes.

### `adapters/__init__.py` — docstring corrected
- Codex entry now says "``--json`` JSONL output, typed ``--output-schema`` and same-session resume".
- OMP entry now says "exact ``--thinking`` value, non-interactive ``-p``, ``--auto-approve``".

### Tests repaired: `tests/protocol_v3/test_harness_policy.py`
- `TestCodexCommandPlan` (9 tests): asserts exact new-dispatch and resumed-dispatch plan shapes; `--json` present, `--jsonl` absent; no `--resume` flag on `exec`; `resume` subcommand token present when session_id supplied.
- `TestCodexDispatch.test_codex_dispatch_passes_full_command_plan`: checks `--json` (not `--jsonl`); dispatcher-driven dispatch has no `resume` (no session_id forwarded).
- `TestOmpCommandPlan` (11+ parametrized = 16 test cases): parametrized effort→thinking mapping for all 6 valid efforts; asserts `-p` present, `--yes` absent; `--auto-approve` present; unsupported effort raises `ValueError`; `on` never emitted.
- `TestOmpDispatch.test_omp_dispatch_passes_full_command_plan`: checks `-p`, `--auto-approve`; no `--resume`, no `--yes` on dispatcher-driven dispatch.
- `TestCrossProductSameSessionRecovery` (9 tests): completely rewritten — new dispatch has no resume (Codex+OMP); resumed dispatch uses `exec resume SID` (Codex) / `--resume SID` (OMP) only with explicit `session_id`; **idempotency key never appears in any plan** (proven for both adapters via dispatcher-driven capture); different session ids produce different resume targets; direct `adapter.dispatch(request, session_id=...)` produces correct resume plan + typed receipt.

## Artifacts And Evidence

| File | Change | Size | Verification |
|---|---|---|---|
| `adapters/codex_app.py` | Rewritten | 12361 bytes | Ruff OK, format OK, compile OK |
| `adapters/omp_cli.py` | Rewritten | 15018 bytes | Ruff OK, format OK, compile OK |
| `adapters/__init__.py` | Docstring edited | 49 lines | Ruff OK, format OK, compile OK |
| `tests/protocol_v3/test_harness_policy.py` | CLI portions repaired | 2055 lines | Ruff OK, format OK, compile OK |

**Confirmed command plan shapes (matching observed local help):**
```
CODEX new:     ['exec', '--model', 'M', '--json', '--output-schema', 'S']
CODEX resume:  ['exec', 'resume', 'SESS', '--model', 'M', '--json', '--output-schema', 'S']
OMP new:       ['--provider', 'P', '--model', 'M', '--thinking', 'max', '-p', '--auto-approve', '--max-time', '3600']
OMP none:      ['--provider', 'P', '--model', 'M', '--thinking', 'off', '-p', '--auto-approve', '--max-time', '3600']
OMP resume:    ['--provider', 'P', '--model', 'M', '--thinking', 'high', '-p', '--auto-approve', '--max-time', '3600', '--resume', 'SESS']
```

## Commands And Observations

| Command | Observation |
|---|---|
| `codex exec --help` | Confirmed `--json`, `--output-schema`, `--model`; no `--jsonl`, no `--resume` |
| `codex exec resume --help` | Confirmed `exec resume [OPTIONS] [SESSION_ID]`; supports `--json`, `--output-schema`, `--model` |
| `omp --help` | Confirmed `-p, --print`, `--auto-approve`, `--thinking` set, `--max-time`, `--resume`, `--no-tools`; no `--yes`; `on` not in thinking set |
| `python3 -m pytest tests/protocol_v3/test_harness_policy.py -q` | **118 passed** in 0.42s |
| `python3 -m pytest tests/protocol_v3/test_harness_policy.py tests/protocol_v3/test_registry_loading.py -q` | **149 passed** in 0.49s (Task 1.7 pair) |
| `python3 -m pytest tests/protocol_v3/ -q` | **819 passed** in 5.95s (full Protocol v3 suite, no regressions) |
| `python3 -m ruff check <4 owned files>` | **OK** |
| `python3 -m ruff format --check <4 owned files>` | **4 files already formatted** |
| `python3 -m py_compile <4 owned files>` | **compile OK** |
| `git status --porcelain \| grep -ic monitoring` | **0** medical-monitoring changes |

## Blockers Or Missing Environment

None. All tools available: `python3`, `pytest`, `ruff 0.15.12`, bundled `codex` executable, local `omp` v17.2.9 executable. PYTHONPATH set to `services/api:packages:.` (existing convention).

**Design note:** `HarnessDispatcher.dispatch()` (owned by worker 02, not in my write set) calls `adapter.dispatch(request)` at line 708 without forwarding a `session_id`. This means a dispatcher-driven dispatch always produces a new plan (no resume). Same-session recovery requires calling `adapter.dispatch(request, session_id=SID)` or `adapter.build_command_plan(request, session_id=SID)` directly. This is correct per the Task 1.6 reservation semantics — the dispatcher manages probe + credential scan, while the caller controls session recovery explicitly. If the manager wants the dispatcher to forward `provider_session_id` from the `NodeExecutionContract`, that would require a coordinated change to `harness.py` (worker 02's file) plus a `provider_session_id` field on `HarnessDispatchRequest` — out of scope for this repair.

## Rerun Requests Or Next Step

**Worker 03 recovery 01 is complete.** All 5 confirmed P1 defects repaired and verified against authoritative local CLI help:
1. `--jsonl` → `--json` (Codex)
2. `--resume` flag → `exec resume SESSION_ID` subcommand (Codex)
3. `--yes` → `-p` + `--auto-approve` (OMP)
4. `--thinking on` → exact effort value; unsupported efforts rejected (OMP)
5. `idempotency_key` no longer used as session id; explicit nullable `session_id` parameter on `build_command_plan`/`dispatch` (both adapters)

118 harness policy tests pass; 149 Task 1.7 pair pass; 819 full Protocol v3 suite pass; Ruff clean; zero medical-monitoring diff. Do not claim final READY — Codex and the independent verifier own acceptance.
