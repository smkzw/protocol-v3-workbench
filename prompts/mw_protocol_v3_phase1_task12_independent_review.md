# MODE=CONFERENCE — Protocol v3 Task 1.2 independent functional review

You are the isolated verifier.

## Hard boundaries

- Work only inside the current workspace and perform a read-only review.
- Do not modify files. Do not start services, browser, model runtimes, OCR or translation.
- Do not perform security, adversarial, permission, path, symlink, TOCTOU,
  malicious-input, destructive-state or penetration testing. This is a functional
  contract and Chinese product-copy review only.
- Runner-managed output path: `runs/codex_mw_protocol_v3_phase1_task12_independent_luna.md`.
  Never invoke a write/edit tool on this report path; return the complete report
  in the final response and let the runner persist it.

Read these files only:

- `services/api/app/protocol_workflow/errors.py`
- `tests/protocol_v3/test_error_codes.py`
- `.hermes/plans/2026-08-09_020923-mw-protocol-multi-agent-rearchitecture.md`, Task 1.2
- `plans/mw_protocol_multi_agent_rearchitecture_design_20260809.md`, Sections 17–19

Primary evidence: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest
tests/protocol_v3/test_error_codes.py -q` returned 20 passed; `git diff --check`
passed. Treat that as an anchor to assess, not as a substitute for source review.

Acceptance criteria:

1. `MW-PRO-<GATE>-<OBJECT>-<CAUSE>` parsing is deterministic and the runtime
   registry is finite; well-formed unknown codes do not silently enter the system.
2. Catalog coverage includes phases 0–8 and E0/E1/E2/E3/D1/W1/Q1/F1 plus the
   exact causes CAS, STALE, UNKNOWN_OUTCOME, CHECKPOINT_EVENT_MISMATCH and
   WORD_RECEIPT_STALE.
3. Every definition has a stable owner, retryability, recovery action, native
   Chinese public message and native Chinese next step.
4. `ProtocolWorkflowError` rejects missing object identity, owner and
   retryability; runtime owner/retryability cannot contradict the registry.
5. The UI payload excludes code, object identity, audit detail/context and
   implementation wording. The audit payload retains complete machine context.
6. Public wording is natural for a senior Chinese medical writer; no programmer,
   backend, log or raw English label is presented as user-facing copy.
7. Scope stays isolated from legacy medical-writing behavior and all
   medical-monitoring files.

Return exactly one verdict line `READY` or `NOT_READY`, followed only by concrete
P0/P1/P2 findings. Cite file and line. Do not suggest optional enhancements when
all acceptance criteria pass.
