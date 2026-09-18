# Design

Use stdlib zipfile/ElementTree/AST; no Word writer, service, model, or dependency.
Extract a source-bound candidate, not mutable product data. All source paths are
read-only. Heading-style hierarchy and other content objects remain distinct;
OOXML paragraph/table indices and paraId preserve traceability. Record the
135/106 heading baseline and 17 top-level/18 recursive table scopes independently.

Legacy source is medical_writing_protocol_template.py current company nodes,
not a nonexistent v1 JSON. AST extraction avoids runtime import side effects.
Keep original semantic IDs and conditional rules. Mapping dispositions require
explicit target IDs plus rationale; unmatched obligations remain visible, never
default-retired or labeled implemented merely by title similarity.

Files: Plan v2's five named outputs, plus bounded mapping/projection evidence
under new task runs if needed. Registry remains candidate until Codex and fresh
reviewer finish source coverage checks. No PhaseI authority choice here.
