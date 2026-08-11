# Task 1.7 same-session functional acceptance follow-up 5

Resume the same independent session after the prior turn was intentionally
stopped for scope expansion. Re-open the current filesystem; it now includes
complete deterministic snapshots of NodeExecutionContract, SkillDefinition,
RoleEntry and artifacts, in addition to dispatch-time full revalidation.

The user and conference contract explicitly exclude security testing. This
pass is functional-contract acceptance only. Do not use `__closure__`,
`object.__setattr__`, monkeypatching, private-symbol construction, coordinated
mutation of frozen models/evidence/snapshots, bytecode/cache manipulation, or
other hostile same-process techniques. Such techniques were already classified
as out of scope, not product findings.

Using only the public `build_request` / `HarnessDispatcher.dispatch` API,
immutable contract constructors, deterministic fakes, and normal offline test
execution, verify current Task 1.7 against the frozen plan:

- four roles/nine skills and thinking discipline;
- exact Role/Skill/artifact/schema/tool/path/region/sensitivity binding;
- session polarity and same-session recovery;
- adapter harness/provider/model preflight, probe policy, exact gate identity,
  lease classification, typed six-field receipt and accurate dispatched flag;
- fallback lineage binding, payload allowlists, Windows-path rejection and deep
  registry immutability;
- no forbidden one-turn/no-tools flags and no medical-monitoring change.

Read-only only. Do not modify files, start services, or invoke live model, OCR,
translation or medical-monitoring workflows. Return concise `READY` or
`NOT_READY`, P0-P4 counts, exact deterministic evidence, environment-only
limitations and next safe action. READY requires no remaining functional P0-P4
finding in Task 1.7 scope.
