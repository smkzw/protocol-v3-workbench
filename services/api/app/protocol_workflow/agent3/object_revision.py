"""Dispatch one scoped AI object revision to the product model (T12).

Mirrors the chapter-facts derivation transport: real adapter, receipt
artifacts, idempotent content-hash replay.  The worker only produces the
candidate; anchoring and the scoped apply stay in ManuscriptDocumentService.
"""
import hashlib
from datetime import datetime, timezone

OBJECT_REVISION_INSTRUCTION = (
    '根据用户要求，仅对给出的单个对象做范围受限修订，对象边界之外的任何内容都不变。'
    '输出JSON对象：{"replacement_content": "字符串"}。'
    '段落对象：返回修订后的完整段落文字。表格对象：返回与输入完全相同结构的'
    'semantic-structured-table JSON字符串（table.rows/columns结构不变或仅按指令调整）。'
    '研究事实只能来自已确认事实或用户指令，不得编造剂量、终点、疗程或来源；'
    '不得使用模板示例值填补缺口。'

)

_OUTPUT_SCHEMA_REF = 'object-revision.v1'


class ObjectRevisionWorker:
    """One worker per study; progress and locks never cross studies (B09)."""

    def __init__(self, *, storage_path, product_profile='deepseek', adapter_factory=None,
                 clock=None):
        from app.protocol_workflow.artifacts.local_store import LocalArtifactStore
        self._store = LocalArtifactStore(str(storage_path) + '.artifacts')
        self._product_profile = product_profile
        self._adapter_factory = adapter_factory
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.progress = {'running': False, 'applied': 0, 'errors': [],
                         'errors_by_operation': {}, 'candidates': {}}
        self._materials = {}
        self._probe_verified = False

    def _build_adapter(self, key):
        from app.protocol_workflow.runtime.adapters.direct_api import DirectApiAdapter  # noqa: F401
        if self._adapter_factory is not None:
            return self._adapter_factory(key)
        if self._product_profile == 'deepseek':
            from app.protocol_workflow.runtime.adapters.deepseek_api import (
                build_deepseek_api_adapter)
            from app.protocol_workflow.runtime.omp_credentials import (
                resolve_omp_deepseek_key)
            return build_deepseek_api_adapter(
                credential_resolver=resolve_omp_deepseek_key,
                artifact_text_resolver=self._resolver, max_input_bytes=2_000_000,
                receipt_sink=self._receipt_sink(key))
        from app.protocol_workflow.runtime.adapters.zhipu_api import (
            build_zhipu_api_adapter, resolve_omp_zhipu_key)
        return build_zhipu_api_adapter(
            credential_resolver=resolve_omp_zhipu_key,
            artifact_text_resolver=self._resolver, max_input_bytes=2_000_000,
            receipt_sink=self._receipt_sink(key))

    def _receipt_sink(self, key):
        from app.protocol_workflow.agent2.design_workflow import persist_model_response
        def sink(content, receipt):
            return persist_model_response(self._store, key, content, receipt,
                                          created_at=self._clock())
        return sink

    def _resolver(self, ref, sha):
        try:
            return self._materials[(ref, sha)]
        except KeyError:
            raise ValueError('object_revision_input_material_missing') from None

    def _dispatch_batch(self, adapter, material_text, material_sha):
        payload = {
            'output_schema_ref': _OUTPUT_SCHEMA_REF,
            'reasoning_effort': 'max',
            'input_artifacts': [{'ref': 'object-revision-input',
                                 'sha256': material_sha}],
            'node_execution_contract_id': 'nec:object-revision:' + material_sha,
            'logical_call_id': 'call:object-revision:' + material_sha,
            'idempotency_key': 'object-revision.v1',
            'prompt_sha256': hashlib.sha256(
                OBJECT_REVISION_INSTRUCTION.encode('utf-8')).hexdigest(),
        }
        self._materials[('object-revision-input', material_sha)] = material_text
        return adapter._dispatch_fn(payload)

    def _stored_response(self, key):
        from app.protocol_workflow.agent2.design_workflow import read_model_response
        try:
            meta = self._store.get_metadata(key)
        except Exception:  # noqa: BLE001 — absent manifest means nothing stored
            return None
        if meta is None:
            return None
        try:
            return read_model_response(self._store, f'{key}:revision:{meta.revision}')
        except Exception:  # noqa: BLE001 — a torn record is simply not replayable
            return None

    def run(self, material: dict, *, operation_id: str) -> dict:
        """Dispatch the scoped revision request; return the parsed candidate."""
        material_text = _canonical_json(material)
        material_sha = hashlib.sha256(material_text.encode('utf-8')).hexdigest()
        key = 'object-revision-response:' + material_sha[16:]
        from app.protocol_workflow.agent2.design_workflow import read_model_response
        self.progress['running'] = True
        try:
            record = self._stored_response(key)
            if record is None:
                adapter = self._build_adapter(key)
                if not self._probe_verified:
                    if not adapter.probe():
                        raise ValueError('object_revision_product_probe_failed')
                    self._probe_verified = True
                receipt = self._dispatch_batch(adapter, material_text, material_sha)
                record = read_model_response(self._store, receipt['output_artifact_ref'])
                if record['receipt'].get('output_sha256') != receipt['output_sha256']:
                    raise ValueError('object_revision_response_material_mismatch')
            try:
                candidate = _parse_candidate(record['content'])
            except ValueError as exc:
                if str(exc) != 'object_revision_candidate_unparsable':
                    raise
                # One same-model structural correction only. The original
                # response remains immutable; the correction may wrap it in
                # the required JSON object but must not revise its wording.
                correction_material = {
                    'schema_version': 'object-revision-structure-correction.v1',
                    'instruction': (
                        '仅把original_response原样放入replacement_content字符串，'
                        '输出单个JSON对象，不得增删或改写任何医学内容。'),
                    'original_response': record['content'],
                }
                correction_text = _canonical_json(correction_material)
                correction_sha = hashlib.sha256(
                    correction_text.encode('utf-8')).hexdigest()
                correction_key = 'object-revision-correction:' + correction_sha[16:]
                corrected = self._stored_response(correction_key)
                if corrected is None:
                    correction_adapter = self._build_adapter(correction_key)
                    if not self._probe_verified:
                        if not correction_adapter.probe():
                            raise ValueError('object_revision_product_probe_failed')
                        self._probe_verified = True
                    correction_receipt = self._dispatch_batch(
                        correction_adapter, correction_text, correction_sha)
                    corrected = read_model_response(
                        self._store, correction_receipt['output_artifact_ref'])
                    if corrected['receipt'].get('output_sha256') \
                            != correction_receipt['output_sha256']:
                        raise ValueError(
                            'object_revision_response_material_mismatch')
                candidate = _parse_candidate(corrected['content'])
            self.progress['candidates'][operation_id] = candidate
            return candidate
        finally:
            self.progress['running'] = False


def _canonical_json(value) -> str:
    import json
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _parse_candidate(content) -> dict:
    import json
    try:
        parsed = json.loads(content) if isinstance(content, str) else content
    except (TypeError, ValueError):
        raise ValueError('object_revision_candidate_unparsable') from None
    if not isinstance(parsed, dict) or not isinstance(parsed.get('replacement_content'), str) \
            or not parsed['replacement_content'].strip():
        raise ValueError('object_revision_candidate_invalid')
    return parsed
