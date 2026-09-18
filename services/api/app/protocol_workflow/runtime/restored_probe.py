"""Restore the user-authorized existing Zhipu first-use probe evidence."""
import hashlib
import json
from pathlib import Path
from types import MappingProxyType

from .adapters.zhipu_api import DEFAULT_MODEL, DEFAULT_REASONING_EFFORT, PROVIDER_ID
from .harness import ProbePolicy


class RestoredZhipuProbePolicy(ProbePolicy):
    """Reuse historical connectivity evidence; do not claim a new live probe.

    The application supplies the approved receipt path. Other adapter
    identities retain the normal independent first-use policy.
    """

    def __init__(self, receipt_path: str | Path):
        super().__init__()
        raw = Path(receipt_path).read_bytes()
        record = json.loads(raw)
        expected = {'status': 'succeeded', 'physical_calls': 1, 'provider': PROVIDER_ID,
                    'requested_model': DEFAULT_MODEL, 'observed_model': DEFAULT_MODEL,
                    'requested_reasoning_effort': DEFAULT_REASONING_EFFORT}
        if any(record.get(key) != value for key, value in expected.items()):
            raise ValueError('prior_product_probe_does_not_match_profile')
        self.evidence = MappingProxyType({
            **expected, 'record_sha256': hashlib.sha256(raw).hexdigest(),
            'effective_reasoning_effort': record.get('effective_reasoning_effort', 'not_reported_by_server'),
        })
        self._verified_identity = f'direct-api:{PROVIDER_ID}:{DEFAULT_MODEL}'

    def ensure_probed(self, adapter) -> None:
        if adapter.identity == self._verified_identity:
            return
        super().ensure_probed(adapter)

    def clear(self, identity: str | None = None) -> None:
        if identity is None or identity == self._verified_identity:
            self._verified_identity = None
        super().clear(identity)
