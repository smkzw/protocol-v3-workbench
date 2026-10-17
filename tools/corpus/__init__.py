"""WP-M2-CORPUS: competitor corpus retrieval → classification → ranking pipeline.

Modules:
- query_templates: data-configurable retrieval query combination templates.
- retrieve: ClinicalTrials.gov API v2 retrieval (with offline fixture degradation).
- classify_rank: category assignment + priority scoring → CompetitorSet JSON.
- fixtures: synthetic study records for offline self-test (test data only).
- selftest: runnable self-test (offline always; online when network available).

Run: python3 tools/corpus/selftest.py [--offline-only]
"""
