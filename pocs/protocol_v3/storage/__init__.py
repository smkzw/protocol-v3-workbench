"""Protocol v3 storage PoC — Task 1.8.

Database-neutral contract suite and a fixed-SQLite-3.53.1 adapter that prove
CAS / outbox / replay / backup / restore / crash / rollback under the frozen
benchmark workload (8 writers, 1,000 CAS operations, 10,000 events).

This package is a PoC artifact under ``pocs/protocol_v3/storage/``.  It MUST
NOT be imported by product code.  The storage-neutral ports it exercises live
in ``app.protocol_workflow.ports``; the SQLite adapter is a candidate
implementation of those ports, not a product module.
"""

from __future__ import annotations
