from __future__ import annotations

import copy
import io
import tempfile
import unittest
import urllib.error
from email.message import Message
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from packages.contracts.workbench_contracts import (
    WritingReferenceSearchCreateRequest,
    WritingReferenceSearchRequest,
)
from services.api.app.writing_reference import (
    ClinicalTrialsGovClient,
    WritingReferenceDiscoveryService,
)
from services.api.app.writing_reference_repository import WritingReferenceRepository
from tests.test_writing_reference import study_fixture


NOW = datetime(2026, 7, 12, 4, 0, tzinfo=timezone.utc)


class FakeCtgovClient:
    def __init__(self, *, total_count: int = 2):
        second = copy.deepcopy(study_fixture())
        second["protocolSection"]["identificationModule"]["nctId"] = "NCT02946463"
        second["protocolSection"]["identificationModule"]["briefTitle"] = "Second Study"
        self.total_count = total_count
        self.first = study_fixture()
        self.second = second
        self.urls = []

    def fetch_json(self, url: str) -> dict:
        self.urls.append(url)
        if url.endswith("/version"):
            return {"apiVersion": "2.0.5", "dataTimestamp": "2026-07-10T09:00:05"}
        if "pageToken=next-2" in url:
            return {"studies": [self.second]}
        return {
            "totalCount": self.total_count,
            "studies": [self.first],
            "nextPageToken": "next-2",
        }


class _JsonResponse:
    def __init__(self, payload: bytes):
        self.payload = payload
        self.headers = {
            "Content-Type": "application/json",
            "Content-Length": str(len(payload)),
        }

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit: int) -> bytes:
        return self.payload

    def geturl(self) -> str:
        return "https://clinicaltrials.gov/api/v2/version"


class WritingReferenceDiscoveryServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = WritingReferenceRepository(Path(self.tmp.name) / "writing_reference.sqlite3")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def request(self) -> WritingReferenceSearchCreateRequest:
        return WritingReferenceSearchCreateRequest(
            search=WritingReferenceSearchRequest(
                indication="Atopic Dermatitis",
                phases=["PHASE2"],
                page_size=100,
            ),
            actor="medical_manager",
            idempotency_key="ctgov-search-ad-phase2",
        )

    def test_client_retries_transient_500_with_bounded_backoff(self) -> None:
        headers = Message()
        headers["Retry-After"] = "2"
        transient = urllib.error.HTTPError(
            "https://clinicaltrials.gov/api/v2/version",
            500,
            "Internal Server Error",
            headers,
            io.BytesIO(b""),
        )
        response = _JsonResponse(b'{"apiVersion":"2.0.5"}')
        delays: list[float] = []
        opener = Mock()
        opener.open.side_effect = [transient, response]
        client = ClinicalTrialsGovClient(sleep=delays.append)

        with patch("services.api.app.writing_reference.urllib.request.build_opener", return_value=opener):
            result = client.fetch_json(
                "https://clinicaltrials.gov/api/v2/version"
            )

        self.assertEqual({"apiVersion": "2.0.5"}, result)
        self.assertEqual([2.0], delays)
        self.assertEqual(2, opener.open.call_count)

    def test_client_does_not_retry_non_transient_404(self) -> None:
        error = urllib.error.HTTPError(
            "https://clinicaltrials.gov/api/v2/version",
            404,
            "Not Found",
            Message(),
            io.BytesIO(b""),
        )
        opener = Mock()
        opener.open.side_effect = error
        client = ClinicalTrialsGovClient(sleep=lambda _delay: None)

        with patch("services.api.app.writing_reference.urllib.request.build_opener", return_value=opener):
            with self.assertRaises(urllib.error.HTTPError):
                client.fetch_json(
                    "https://clinicaltrials.gov/api/v2/version"
                )
        self.assertEqual(1, opener.open.call_count)

    def test_live_discovery_contract_paginates_and_persists_reproducible_snapshot(self) -> None:
        client = FakeCtgovClient()
        service = WritingReferenceDiscoveryService(self.repo, client, clock=lambda: NOW)

        snapshot = service.create_search_snapshot("proj_rux_03_002", self.request())

        self.assertEqual(2, snapshot.total_count)
        self.assertEqual(2, snapshot.returned_count)
        self.assertEqual(2, snapshot.page_count)
        self.assertEqual({"NCT05014438", "NCT02946463"}, {item.nct_id for item in snapshot.candidates})
        self.assertEqual("2.0.5", snapshot.api_version)
        self.assertEqual("2026-07-10T09:00:05", snapshot.data_timestamp)
        self.assertEqual(3, len(client.urls))

        replay = service.create_search_snapshot("proj_rux_03_002", self.request())
        self.assertEqual(snapshot.model_dump(), replay.model_dump())

    def test_pagination_count_mismatch_fails_without_persisting_partial_snapshot(self) -> None:
        service = WritingReferenceDiscoveryService(
            self.repo,
            FakeCtgovClient(total_count=3),
            clock=lambda: NOW,
        )

        with self.assertRaisesRegex(RuntimeError, "count mismatch"):
            service.create_search_snapshot("proj_rux_03_002", self.request())

        with self.assertRaises(KeyError):
            self.repo.search_snapshot("proj_rux_03_002", service.snapshot_id("proj_rux_03_002", self.request()))

    def test_idempotent_replay_ignores_runtime_created_at_changes(self) -> None:
        ticks = iter([NOW, NOW + timedelta(minutes=5)])
        service = WritingReferenceDiscoveryService(
            self.repo,
            FakeCtgovClient(),
            clock=lambda: next(ticks),
        )

        first = service.create_search_snapshot("proj_rux_03_002", self.request())
        replayed = service.create_search_snapshot("proj_rux_03_002", self.request())

        self.assertEqual(first.model_dump(), replayed.model_dump())


if __name__ == "__main__":
    unittest.main()
