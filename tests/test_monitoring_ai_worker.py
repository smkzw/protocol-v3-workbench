from __future__ import annotations

from threading import Event, Lock
from types import SimpleNamespace

import pytest

from services.api.app.monitoring_ai_worker import MonitoringAiWorker


class FakeService:
    def __init__(self, work_items: int):
        self.remaining = work_items
        self.processed = 0
        self.owners = set()
        self.lock = Lock()
        self.done = Event()

    def run_next(self, owner: str):
        with self.lock:
            self.owners.add(owner)
            if self.remaining == 0:
                if self.processed:
                    self.done.set()
                return SimpleNamespace(processed=False)
            self.remaining -= 1
            self.processed += 1
            if self.remaining == 0:
                self.done.set()
        return SimpleNamespace(processed=True)


class LeaseLostService:
    def __init__(self):
        self.calls = 0
        self.done = Event()

    def run_next(self, owner: str):
        self.calls += 1
        if self.calls == 1:
            return SimpleNamespace(processed=False, lease_lost=True)
        if self.calls == 2:
            self.done.set()
            return SimpleNamespace(processed=True, lease_lost=False)
        return SimpleNamespace(processed=False, lease_lost=False)


def test_worker_drains_durable_queue_with_bounded_parallelism() -> None:
    service = FakeService(25)
    worker = MonitoringAiWorker(service, parallelism=4)

    started = worker.wake()

    assert 1 <= started <= 4
    assert service.done.wait(timeout=2)
    assert service.processed == 25
    assert service.remaining == 0
    assert len(service.owners) <= 4


def test_worker_continues_after_superseded_inflight_job_loses_lease() -> None:
    service = LeaseLostService()
    worker = MonitoringAiWorker(service, parallelism=1)

    worker.wake()

    assert service.done.wait(timeout=2)
    assert service.calls >= 2


@pytest.mark.parametrize("parallelism", [0, 17])
def test_worker_rejects_unbounded_parallelism(parallelism: int) -> None:
    with pytest.raises(ValueError, match="parallelism"):
        MonitoringAiWorker(FakeService(0), parallelism=parallelism)
