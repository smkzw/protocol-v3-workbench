# Design

Keep v1 classes untouched; add explicitly versioned v2 models using existing
Pydantic immutable conventions. No database/service changes or new dependencies.
Compose a small number of typed value contracts rather than untyped dictionaries
or a second workflow engine. Reuse enums and validation helpers where suitable.
SemanticBlock provenance reform is a later consumer integration, not permission
to weaken v1 block requirements in this task. Contract source requirements must
support template/control objects without inventing medical claims.

Allowed implementation: packages/contracts/workbench_contracts/protocol_v3.py
and tests/protocol_v3/test_chapter_contract_schema.py. New test evidence in
runs/mw_protocol_v3_3r2_contracts_20260906/. No writes to accepted3R1registry.
Phase3R1candidateaccepted, source findings feed3R3; currentdesignation notactivated.
