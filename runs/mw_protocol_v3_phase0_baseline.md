# MW Protocol v3 Phase 0 baseline

Status: `TASK_0_1_REMEDIATED_AWAITING_SAME_SESSION_REVIEW`
Task ID: `mw_protocol_v3_phase0_20260809_111313`  
Created: 2026-08-09  

## Authority and scope

- Approved implementation plan: `.hermes/plans/2026-08-09_020923-mw-protocol-multi-agent-rearchitecture.md`
- Approved plan SHA-256: `fa99fbd38588a5d3a8f35d3936c3e84c26cfd4a9eea58d8aa739e93363d54914`
- Design baseline SHA-256 expected by the plan: `321169afc9f33f572b803661b6c6eeb598304267fcb33cdf7de4faf0b00ad0d8`
- D001–D017 decision record SHA-256 expected by the plan: `04d99dd3cb239c49f5de52d1b0fe0fdd959007def509e0931907614894eb816a`
- Current filesystem is authoritative. This record does not claim recovery of deleted parent-session dialogue.
- Protocol only. CSR and an independent Synopsis workflow remain out of scope.
- Medical-monitoring source, tests, runtime and evidence are protected and must not be mutated by this work.

## DC-018 approval boundary

The user-authorized implementation goal points to the approved plan. Therefore the plan's DC-018 clarification is active for implementation: the application-owned authority graph is canonical; LangGraph remains a preferred candidate and becomes selected only after P2-G2. A separate immutable decision record will be created in Task 0.4 without rewriting design-v1.2.

## Source-only baseline

- Live evidence root: `/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/workbench`
- Live Git status at intake: no Git repository found in the workbench or its parents.
- Authority snapshot: `/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-snapshots/mw_protocol_v3_phase0_20260809_111313-r3`
- Superseded evidence snapshots: the original v1 and rejected r2 directories remain immutable; r2 incorrectly excluded the legitimate `packages/contracts/workbench_contracts/runtime_contract.json` and must not be used.
- Isolated implementation workspace: `/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313`
- Manifest SHA-256: `cb8c350354129e9fdbfabae71edf82c9dcb5e96264da0aa0c49c4c09c132b122`
- Source tar SHA-256: `f238e8eff899fa7101852cab1f6c82c229604059c3fa62281c1ee935941ba7c7`
- Source content fingerprint: `a9ece82faffde0106dcda2ff2dab29bc79ba1ec6bed94fca87e19606dc64b8f2`
- Source entries: `1,017`
- Source bytes: `54,023,389`
- Planned PoC source paths covered by policy: `33`

The allowlist includes the Phase 0 toolchain manifests (`frontend/package*.json`, both current lock families, Vite config, frontend AGENTS, and current API requirements) as exact files. This is the minimal implementation resolution needed to make Task 0.3 reproducible; it does not allow the rest of either parent directory.

## Exclusions

The baseline excludes runtime, credentials, SQLite/WAL/SHM, `.venv`, `node_modules`, caches, dist, logs, runs, records, evidence, archives, historical backups, PoC results, PoC DOCX/PDF, OpenXML Release/obj intermediates and frontend test evidence images. It retains the published OpenXML validator binary and source/licence surfaces covered by the source allowlist.

## Verification evidence

1. External TDD red: `python3 -m unittest -v test_source_baseline.py` failed with `ModuleNotFoundError: build_source_baseline` before implementation.
2. Fresh verification exposed a v1 policy gap for compound WAL/SHM and generic cache names. New tests failed on 9 cases before remediation.
3. External TDD green: 11/11 source-policy, manifest, symlink, traversal and exact tar-member tests passed. The same 11 tests passed inside this isolated workspace.
4. `verify_source_baseline.py` checked both checksum lines, rejected duplicate/extra tar members, safely extracted the tar, matched all 1,017 entries and content fingerprint, and reverified live with strict metadata.
5. Git is initialized only in this isolated workspace; no remote is configured.

## Concurrent-owner attribution

The fresh verifier observed post-intake changes only under the active medical-monitoring owner surfaces (`poc/medical_monitoring_ai_native_r1`, matching monitoring run records) plus shared test cache. Those paths are outside the Protocol source allowlist. Every one of the 1,017 allowlisted writing-source entries remained byte/size/mode/mtime identical and no task-ID path or live `.git` appeared. Stopping that owner would contradict the user's explicit parallel-development requirement; Task 0.4 will freeze its then-current resolved paths and enforce deny-mutation before repository hygiene begins. Unknown-owner or shared-source deltas remain fail-closed.

## Next safe action

Commit the remediation in the isolated Git workspace, then obtain a same-session independent re-review. Only after explicit Task 0.1 acceptance may Task 0.2 begin.
