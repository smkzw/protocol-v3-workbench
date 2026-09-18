# Design preparation — not implementation approval evidence

## Existing seams

- Product storage/sqlite.py owns both outbox_message and inbox_result; both ports
  participate in one UoW. events/unit_of_work.py consumes these ports separately.
- Standalone inbox results are valid in existing repository contracts. Outbox
  currently requires request metadata. Do not invent request IDs to merge rows.
- events/inbox.py applies semantic effect before consumed marker. The result
  receipt is not the semantic completion marker.
- ReservationStatus already contains two active states plus three terminals;
  ExecutionTerminalState already supplies the compact result enum.
- ProtocolV3Model.material_sha256 includes dependency tuples, and harness input
  binding compares exact ordered artifact hashes. Removing fields changes proof
  of input freshness unless replaced by an explicit versioned dependency digest.

## Implementation decisions to resolve from source

Prefer additive outbox result columns for normal paired work with a compatible
read-through of preserved historical inbox rows. Define truthful standalone
result representation before choosing migration SQL. Avoid permanent duplicate
writes: the new path must have one authoritative result store. Historic rows
remain evidence, not competing mutable authority. No migration of live projects.

Compact new contract serialization must retain enough dependency information for
actual input binding, while accepting legacy serialized fields through explicit
version handling. Preserve historical event hashes. Pure reconstruction added in
1R.3 must remain independent of current aggregate snapshots.

This is a bounded design input, not a claim that these choices have been built.
Confirm exact migration and serialization against tests before implementation.

## Contract compaction source findings and next implementation checks

Four affected contracts: SemanticDocumentRevision, ChapterLockSnapshot,
NodeExecutionContract, SubmissionEvidencePackage. The ordered input tuple is
actively checked by runtime/harness.py:_validate_artifact_binding; document
chapter hashes enter canonical/document.py:_document_payload_sha256 and revision
construction. The other two remain contract surfaces without current product
constructors. Do not equate absent current callers with permission to drop their
declared provenance obligations.

Implement explicit minor-version dependency compaction, accepting legacy v1
without rewriting its serialized payload/material hash. New representation may
use a domain-separated digest of the exact ordered dependency tuple, bound into
the top-level material payload. Omission, replacement, order changes and chapter
contract changes must still change that binding. Avoid a second database registry
or per-field hash framework. Reject inconsistent supplied tuple/digest pairs;
do not silently choose whichever happens to pass. Preserve raw historical event
bytes; migration returns a new version rather than rewriting immutable rows.

Required tests: legacy material golden comparison; explicit conversion roundtrip;
each substantive dependency mutation invalidates; real harness accepts matching
artifacts and rejects missing/reordered/substituted inputs; document revision/CAS
replay uses the appropriate version. Expose a usable current construction path
and track its typed-facade adoption in2R.1, not an unused parallel contract class.
This subsection is implementation input, not completed functionality.
