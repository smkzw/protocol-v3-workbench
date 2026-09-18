"""Shared synthetic fixtures for C03 followup probes (scratch-only)."""
import time

from test_zhipu_product_transport import _FakeOpener


class GatedOpener(_FakeOpener):
    """Signals entry via a marker file, then blocks inside the transport.

    The dispatching process is expected to be killed while blocked; the
    per-reservation flock stays held until process death releases it.
    """

    def __init__(self, outcomes, marker_file):
        super().__init__(outcomes)
        self.marker_file = marker_file

    def open(self, request, timeout=None):
        self.marker_file.write_text("entered", encoding="utf-8")
        while True:
            time.sleep(0.2)
