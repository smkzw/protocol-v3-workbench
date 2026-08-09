# MW Protocol v3 Phase 0 baseline

Status: `TASK_0_1_IMPLEMENTATION_IN_PROGRESS`  
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
- Snapshot: `/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-snapshots/mw_protocol_v3_phase0_20260809_111313`
- Isolated implementation workspace: `/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313`
- Manifest SHA-256: `573852280402e7b5ebf048a993ff46993939e46ee3c616f41b5cf19f8823b453`
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
2. External TDD green: 9/9 source-policy, manifest, symlink and traversal tests passed.
3. `verify_source_baseline.py` checked both checksum lines, safely extracted the tar, matched all 1,017 entries and content fingerprint, and reverified live with strict metadata.
4. The same 9 tests passed inside this isolated workspace via `python3 -m pytest tests/protocol_v3/test_source_baseline.py -q`.
5. Git is initialized only in this isolated workspace; no remote is configured.

## Next safe action

Finish the isolated baseline commit, then independently verify Task 0.1: live `.git` absent, live source manifest byte/metadata identical, isolated Git clean, tar/checksums reproducible, and no task-created files inside the live evidence root. Only after Task 0.1 acceptance may Task 0.2 begin.
