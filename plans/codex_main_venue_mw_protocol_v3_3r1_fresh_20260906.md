# Codex Main-Venue Plan: mw_protocol_v3_3r1_fresh_20260906

Date: TODO
Objective: Fresh independent read-only source-to-registry acceptance review for Task 3R.1. Read .trellis/tasks/09-06-protocol-v3-3r1/prd.md and design.md, approved TP-MA-07 v2 DOCX at the PRD path, legacy AST sources referenced by extractor, and the five current candidate files scripts/qc/protocol_v3/extract_tp_ma_07_v2_registry.py, tests/protocol_v3/test_tp_ma_07_v2_registry.py, config/medical_writing/protocol_v3/templates/tp_ma_07_v2/{template.json,node_tree.json,v1_to_v2_mapping.json}. Do not read worker reports or private reasoning. Independently check semantic coverage, mapping correctness, applicability defaults, source locators, Word field/section rules, deterministic regeneration and meaningful tests. Counts alone cannot establish complete medical obligations. Candidate only, no source edits, no source DOCX writes, no services/models/network/OCR/translation or production paths. May run offline focused tests using runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python with PYTHONPATH=tests/protocol_v3:services/api:packages:. and no bytecode/cache. Return concrete file/line findings and ACCEPT or REVISE scoped to this candidate, not clinical or Word-render acceptance. Do not clean or archive anything; runner owns report output.

## Task Decomposition

TODO

## Source Packet

TODO

## Participant Assignments

| Role | Provider | Model | Output |
|---|---|---|---|
| `general_single_object` | `opencode-go` | `muse-spark-1.3-contributor` | `runs/conference/mw_protocol_v3_3r1_fresh_20260906/general_single_object.md` |

## Conference Panel Coordination

- No sub-venue chair. Codex leads the assigned panel directly.

## Main-Venue Review

- Codex performs the final synthesis and acceptance.
- This conference mode has no Reasonix second-review role.

## Timeout And Retry Tracking

TODO: Record start/end time, pending/failed/incorporated status, retry reason, and whether late outputs were used.

## Codex Verification Checklist

TODO
