from __future__ import annotations

from threading import Lock, Thread
from uuid import uuid4

from .monitoring_ai_service import MonitoringAiService


class MonitoringAiWorker:
    """Wake-only local worker over the durable monitoring AI queue."""

    def __init__(
        self,
        service: MonitoringAiService,
        *,
        parallelism: int = 4,
    ):
        if not 1 <= parallelism <= 16:
            raise ValueError("monitoring AI worker parallelism must be 1 to 16")
        self.service = service
        self.parallelism = parallelism
        self._lock = Lock()
        self._threads: list[Thread] = []

    def wake(self) -> int:
        with self._lock:
            self._threads = [thread for thread in self._threads if thread.is_alive()]
            started = 0
            while len(self._threads) < self.parallelism:
                thread = Thread(
                    target=self._drain,
                    name=f"monitoring-ai-worker-{len(self._threads) + 1}",
                    daemon=True,
                )
                self._threads.append(thread)
                thread.start()
                started += 1
            return started

    def running(self) -> int:
        with self._lock:
            self._threads = [thread for thread in self._threads if thread.is_alive()]
            return len(self._threads)

    def _drain(self) -> None:
        owner = f"local-monitoring-ai-{uuid4().hex}"
        while True:
            result = self.service.run_next(owner)
            if getattr(result, "lease_lost", False):
                # A newer prompt/input can supersede an in-flight job while
                # the provider call is still returning. That lost lease is
                # expected and must not strand the newer durable queue.
                continue
            if not result.processed:
                return
