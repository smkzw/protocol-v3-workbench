"""Focused deterministic Harness policy tests for Protocol v3 Task 1.7.

This file holds the direct/oMLX portions (worker 02) and the Codex/OMP CLI
adapter portions (worker 03) of the Harness policy test surface.

Design authority: frozen plan Task 1.7 and
``plans/mw_protocol_multi_agent_rearchitecture_design_20260809.md`` sections
17.2 and 18.  All tests are *offline and deterministic*: no service, model,
OCR, translation, repository, gate database or network is started.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from app.protocol_workflow.registries.loader import RoleEntry, _TargetProfile
from app.protocol_workflow.runtime.adapters.codex_app import (
    CodexAppAdapter,
    build_codex_exec_plan,
)
from app.protocol_workflow.runtime.adapters.direct_api import DirectApiAdapter
from app.protocol_workflow.runtime.adapters.local_omlx import (
    LocalOmlxAdapter,
)
from app.protocol_workflow.runtime.adapters.omp_cli import (
    OmpCliAdapter,
    build_omp_cli_plan,
)
from app.protocol_workflow.runtime.harness import (
    AdapterOutcome,
    AdapterProbeError,
    ArtifactRef,
    DispatchReceipt,
    FallbackInput,
    HarnessDispatcher,
    HarnessDispatchRequest,
    HarnessFallbackError,
    HarnessPolicyError,
    ProbePolicy,
    WorkloadGateError,
    build_fallback_request,
    build_request,
)
from app.protocol_workflow.runtime.idempotency import canonical_input_hash

from packages.contracts.workbench_contracts.protocol_v3 import (
    CanonicalState,
    NodeExecutionContract,
    ReasoningEffort,
    SensitivityTier,
    SideEffectKind,
    SkillDefinition,
)

# ---------------------------------------------------------------------------
# Deterministic constants
# ---------------------------------------------------------------------------

OUTPUT_SHA = "a" * 64
PROMPT_SHA = "b" * 64


def _prior_fallback_evidence(
    canonical_source: Mapping[str, Any],
    *,
    logical_call_id: str = "lc:1",
    idempotency_key: str = "idem-1",
) -> dict[str, str]:
    return {
        "previous_logical_call_id": logical_call_id,
        "previous_idempotency_key": idempotency_key,
        "previous_input_sha256": canonical_input_hash(
            logical_call_id=logical_call_id,
            idempotency_key=idempotency_key,
            payload=canonical_source,
        ),
    }


INPUT_ARTIFACT_SHA = "c" * 64
OUTPUT_SCHEMA = "https://protocol-v3.local/schemas/chapter-draft-output.v1.json"
INPUT_SCHEMA = "https://protocol-v3.local/schemas/chapter-draft-input.v1.json"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Registry-bound role helpers
# ---------------------------------------------------------------------------


def _target_profile(
    *,
    provider: str = "deepseek",
    model: str = "deepseek-v4-flash",
    harness: str = "direct-api",
    regions: tuple[str, ...] = ("cn",),
    sensitivity: str = "confidential",
) -> _TargetProfile:
    return _TargetProfile(
        provider=provider,
        model=model,
        harness=harness,
        regions=regions,
        sensitivity_tier=sensitivity,
        declared_runtime_note="test target profile",
    )


def _role_entry(
    *,
    role_id: str = "product-llm",
    role_kind: str = "llm",
    thinking: bool = True,
    default_effort: str = "max",
    allowed_efforts: tuple[str, ...] = ("low", "medium", "high", "max", "xhigh"),
    target: _TargetProfile | None = None,
) -> RoleEntry:
    return RoleEntry(
        role_id=role_id,
        role_kind=role_kind,
        description="test role",
        thinking_configurable=thinking,
        default_effort=default_effort,
        allowed_efforts=allowed_efforts,
        target_profile=target or _target_profile(),
    )


def _llm_role() -> RoleEntry:
    return _role_entry(
        role_id="product-llm",
        role_kind="llm",
        thinking=True,
        target=_target_profile(provider="deepseek", model="deepseek-v4-flash"),
    )


def _ocr_role() -> RoleEntry:
    return _role_entry(
        role_id="product-ocr",
        role_kind="ocr",
        thinking=False,
        default_effort="none",
        allowed_efforts=("none",),
        target=_target_profile(
            provider="paddle-official",
            model="PaddleOCR-VL-1.6",
            harness="direct-api",
        ),
    )


def _translation_role() -> RoleEntry:
    return _role_entry(
        role_id="product-translation",
        role_kind="translation",
        thinking=False,
        default_effort="none",
        allowed_efforts=("none",),
        target=_target_profile(
            provider="local-omlx",
            model="dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX",
            harness="local-omlx",
            regions=("local",),
        ),
    )


def _support_role() -> RoleEntry:
    return _role_entry(
        role_id="product-ocr-translation-support",
        role_kind="ocr_translation_support",
        thinking=True,
    )


# ---------------------------------------------------------------------------
# Artifact / skill / contract helpers
# ---------------------------------------------------------------------------


def _artifact(
    ref: str = "seed",
    sha: str = INPUT_ARTIFACT_SHA,
    snippet: str = "",
) -> ArtifactRef:
    return ArtifactRef(ref=ref, sha256=sha, snippet=snippet)


def _skill(
    *,
    skill_id: str = "skill.chapter-draft",
    input_schema: str = INPUT_SCHEMA,
    output_schema: str = OUTPUT_SCHEMA,
    allowed_tools: tuple[str, ...] = ("deepseek-chat",),
    allowed_paths: tuple[str, ...] = ("artifacts/chapter-draft/",),
) -> SkillDefinition:
    return SkillDefinition(
        skill_definition_id=skill_id,
        skill_version="1.0.0",
        agent_role="full_draft",
        input_schema_ref=input_schema,
        output_schema_ref=output_schema,
        evidence_requirements=("source-bound-content",),
        allowed_tools=allowed_tools,
        allowed_paths=allowed_paths,
        side_effect_kind=SideEffectKind.CANONICAL_PROPOSAL,
        acceptance_test_ids=("at.chapter-draft.1",),
        canonical_state=CanonicalState.FROZEN,
    )


def _node_contract(
    *,
    role: str = "product-llm",
    harness: str = "direct-api",
    provider: str = "deepseek",
    model: str = "deepseek-v4-flash",
    effort: ReasoningEffort = ReasoningEffort.MAX,
    sensitivity: SensitivityTier = SensitivityTier.CONFIDENTIAL,
    allowed_providers: tuple[str, ...] = ("deepseek",),
    allowed_regions: tuple[str, ...] = ("cn",),
    skill_id: str = "skill.chapter-draft",
    allowed_tools: tuple[str, ...] = ("deepseek-chat",),
    allowed_paths: tuple[str, ...] = ("artifacts/chapter-draft/",),
    input_hashes: tuple[str, ...] = (INPUT_ARTIFACT_SHA,),
    provider_session_id: str | None = None,
    same_session_recovery: bool = True,
) -> NodeExecutionContract:
    return NodeExecutionContract(
        node_execution_contract_id="nec:test:1",
        skill_definition_id=skill_id,
        role=role,
        harness=harness,
        provider=provider,
        model=model,
        reasoning_effort=effort,
        provider_session_id=provider_session_id,
        same_session_recovery=same_session_recovery,
        timeout_seconds=300,
        fallback_policy_id="fbp:default",
        prompt_sha256=PROMPT_SHA,
        input_schema_ref=INPUT_SCHEMA,
        output_schema_ref=OUTPUT_SCHEMA,
        allowed_tools=allowed_tools,
        allowed_paths=allowed_paths,
        permission_policy_id="perm:default",
        input_artifact_hashes=input_hashes,
        sensitivity_tier=sensitivity,
        allowed_providers=allowed_providers,
        allowed_regions=allowed_regions,
        redaction_policy_id="red:default",
        retention_policy_id="ret:default",
        logical_call_id="lc:chapter-1-draft:1",
        idempotency_key="idem-1",
    )


def _build_llm_request(
    *,
    artifacts: tuple[ArtifactRef, ...] = (_artifact(),),
    selected_region: str = "cn",
) -> Any:
    return build_request(
        node_contract=_node_contract(),
        skill=_skill(),
        role_entry=_llm_role(),
        artifacts=artifacts,
        selected_region=selected_region,
    )


# ---------------------------------------------------------------------------
# Deterministic fakes
# ---------------------------------------------------------------------------


class _FakeDirectApi:
    """Deterministic Direct API fake."""

    def __init__(
        self,
        *,
        receipt: Mapping[str, str] | None = None,
        probe_ok: bool = True,
        capture: list[dict[str, Any]] | None = None,
    ) -> None:
        self._receipt = receipt or {
            "provider_session_id": "sess-direct-1",
            "output_sha256": OUTPUT_SHA,
            "observed_provider": "deepseek",
            "observed_model": "deepseek-v4-flash",
            "output_artifact_ref": "chapter-1-draft",
            "output_schema_ref": OUTPUT_SCHEMA,
        }
        self.probe_ok = probe_ok
        self.probe_calls = 0
        self.invocations = 0
        self.capture = capture

    def probe(self) -> bool:
        self.probe_calls += 1
        return self.probe_ok

    def __call__(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.invocations += 1
        if self.capture is not None:
            self.capture.append(payload)
        return dict(self._receipt)


class _FakeOmlxGate:
    """Deterministic fake of the shared workload-gate lease factory."""

    def __init__(self, *, gate_selection: Mapping[str, Any] | None = None) -> None:
        self.gate_selection = dict(gate_selection) if gate_selection else {}
        self.acquired: list[tuple[str, str]] = []
        self.released: list[str] = []
        self.active_lease: Mapping[str, Any] | None = None

    @contextmanager
    def lease(self, *, kind: str, owner: str) -> Iterator[Mapping[str, Any]]:
        lease_id = f"lease-{kind}-{len(self.acquired)}"
        lease = {"lease_id": lease_id, "kind": kind, "owner": owner}
        self.acquired.append((kind, owner))
        self.active_lease = lease
        try:
            yield lease
        finally:
            self.active_lease = None
            self.released.append(lease_id)


class _FakeOmlxDispatch:
    """Deterministic oMLX dispatch fake."""

    def __init__(
        self,
        *,
        receipt: Mapping[str, str] | None = None,
        capture: list[tuple[dict[str, Any], Mapping[str, Any]]] | None = None,
    ) -> None:
        self._receipt = receipt or {
            "provider_session_id": "sess-omlx-1",
            "output_sha256": OUTPUT_SHA,
            "observed_provider": "local-omlx",
            "observed_model": "dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX",
            "output_artifact_ref": "translation-out",
            "output_schema_ref": OUTPUT_SCHEMA,
        }
        self.invocations = 0
        self.capture = capture

    def probe(self) -> bool:
        return True

    def __call__(
        self,
        payload: dict[str, Any],
        lease: Mapping[str, Any],
    ) -> dict[str, Any]:
        self.invocations += 1
        if self.capture is not None:
            self.capture.append((payload, lease))
        return dict(self._receipt)


class _FakeCodexTransport:
    """Deterministic Codex process/session transport fake."""

    def __init__(
        self,
        *,
        receipt: Mapping[str, str] | None = None,
        capture: list[tuple[list[str], dict[str, Any]]] | None = None,
    ) -> None:
        self._receipt = receipt or {
            "provider_session_id": "sess-codex-1",
            "output_sha256": OUTPUT_SHA,
            "observed_provider": "codex-app",
            "observed_model": "deepseek-v4-flash",
            "output_artifact_ref": "codex-out",
            "output_schema_ref": OUTPUT_SCHEMA,
        }
        self.invocations = 0
        self.capture = capture
        self.probe_ok = True
        self.probe_calls = 0

    def probe(self) -> bool:
        self.probe_calls += 1
        return self.probe_ok

    def __call__(self, plan: list[str], payload: dict[str, Any]) -> dict[str, Any]:
        self.invocations += 1
        if self.capture is not None:
            self.capture.append((list(plan), payload))
        return dict(self._receipt)


class _FakeOmpTransport:
    """Deterministic OMP process/session transport fake."""

    def __init__(
        self,
        *,
        receipt: Mapping[str, str] | None = None,
        capture: list[tuple[list[str], dict[str, Any]]] | None = None,
    ) -> None:
        self._receipt = receipt or {
            "provider_session_id": "sess-omp-1",
            "output_sha256": OUTPUT_SHA,
            "observed_provider": "omp-cli",
            "observed_model": "deepseek-v4-flash",
            "output_artifact_ref": "omp-out",
            "output_schema_ref": OUTPUT_SCHEMA,
        }
        self.invocations = 0
        self.capture = capture
        self.probe_ok = True
        self.probe_calls = 0

    def probe(self) -> bool:
        self.probe_calls += 1
        return self.probe_ok

    def __call__(self, plan: list[str], payload: dict[str, Any]) -> dict[str, Any]:
        self.invocations += 1
        if self.capture is not None:
            self.capture.append((list(plan), payload))
        return dict(self._receipt)


# ---------------------------------------------------------------------------
# Codex schema-path resolver (URI → local JSON Schema file)
# ---------------------------------------------------------------------------

#: Module-level cache for the temp schema file created by the default resolver.
#: Populated on first access; cleaned up at process exit by TemporaryDirectory.
_schema_tmpdir: Any = None
_schema_file_cache: dict[str, str] = {}


def _ensure_schema_file(schema_ref: str = OUTPUT_SCHEMA) -> str:
    """Create (once) and return the path to a temp JSON Schema file for *schema_ref*.

    The file is a minimal valid JSON Schema so ``os.path.isfile`` passes.
    """
    global _schema_tmpdir
    if schema_ref in _schema_file_cache:
        return _schema_file_cache[schema_ref]
    if _schema_tmpdir is None:
        import tempfile

        _schema_tmpdir = tempfile.TemporaryDirectory(prefix="codex-schema-")
    file_path = os.path.join(_schema_tmpdir.name, "output-schema.json")
    Path(file_path).write_text('{"type": "object"}', encoding="utf-8")
    _schema_file_cache[schema_ref] = file_path
    return file_path


def _default_schema_resolver(schema_ref: str) -> str | None:
    """Deterministic resolver: maps the canonical output schema URI to a temp file."""
    if schema_ref == OUTPUT_SCHEMA:
        return _ensure_schema_file(schema_ref)
    return None


# ---------------------------------------------------------------------------
# Adapter factory helpers (all include mandatory probe_fn)
# ---------------------------------------------------------------------------


def _direct_adapter(fake: _FakeDirectApi | None = None) -> DirectApiAdapter:
    f = fake or _FakeDirectApi()
    return DirectApiAdapter(
        provider="deepseek",
        model="deepseek-v4-flash",
        dispatch_fn=f,
        probe_fn=f.probe,
    )


def _omlx_adapter(
    fake: _FakeOmlxDispatch | None = None,
) -> LocalOmlxAdapter:
    f = fake or _FakeOmlxDispatch()
    return LocalOmlxAdapter(
        provider="local-omlx",
        model="dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX",
        dispatch_fn=f,
        probe_fn=f.probe,
    )


def _codex_adapter(
    fake: _FakeCodexTransport | None = None,
    *,
    schema_path_resolver: Any = None,
) -> CodexAppAdapter:
    f = fake or _FakeCodexTransport()
    return CodexAppAdapter(
        provider="codex-app",
        model="deepseek-v4-flash",
        transport=f,
        probe_fn=f.probe,
        schema_path_resolver=schema_path_resolver or _default_schema_resolver,
    )


def _omp_adapter(fake: _FakeOmpTransport | None = None) -> OmpCliAdapter:
    f = fake or _FakeOmpTransport()
    return OmpCliAdapter(
        provider="omp-cli",
        model="deepseek-v4-flash",
        transport=f,
        probe_fn=f.probe,
    )


# ---------------------------------------------------------------------------
# Codex / OMP request helpers (LLM role, codex/omp provider)
# ---------------------------------------------------------------------------


def _codex_node_contract(
    *,
    role: str = "product-llm",
    provider: str = "codex-app",
    model: str = "deepseek-v4-flash",
    effort: ReasoningEffort = ReasoningEffort.MAX,
    sensitivity: SensitivityTier = SensitivityTier.CONFIDENTIAL,
    allowed_providers: tuple[str, ...] = ("codex-app",),
    allowed_regions: tuple[str, ...] = ("cn",),
    provider_session_id: str | None = None,
) -> NodeExecutionContract:
    return _node_contract(
        role=role,
        harness="codex-app",
        provider=provider,
        model=model,
        effort=effort,
        sensitivity=sensitivity,
        allowed_providers=allowed_providers,
        allowed_regions=allowed_regions,
        provider_session_id=provider_session_id,
    )


def _codex_role() -> RoleEntry:
    return _role_entry(
        role_id="product-llm",
        role_kind="llm",
        thinking=True,
        target=_target_profile(
            provider="codex-app", model="deepseek-v4-flash", harness="codex-app"
        ),
    )


def _codex_request(*, effort: ReasoningEffort = ReasoningEffort.MAX) -> Any:
    return build_request(
        node_contract=_codex_node_contract(effort=effort),
        skill=_skill(),
        role_entry=_codex_role(),
        artifacts=(_artifact(),),
        selected_region="cn",
    )


def _omp_node_contract(
    *,
    role: str = "product-llm",
    provider: str = "omp-cli",
    model: str = "deepseek-v4-flash",
    effort: ReasoningEffort = ReasoningEffort.MAX,
    sensitivity: SensitivityTier = SensitivityTier.CONFIDENTIAL,
    allowed_providers: tuple[str, ...] = ("omp-cli",),
    allowed_regions: tuple[str, ...] = ("cn",),
    provider_session_id: str | None = None,
) -> NodeExecutionContract:
    return _node_contract(
        role=role,
        harness="omp-cli",
        provider=provider,
        model=model,
        effort=effort,
        sensitivity=sensitivity,
        allowed_providers=allowed_providers,
        allowed_regions=allowed_regions,
        provider_session_id=provider_session_id,
    )


def _omp_role() -> RoleEntry:
    return _role_entry(
        role_id="product-llm",
        role_kind="llm",
        thinking=True,
        target=_target_profile(
            provider="omp-cli", model="deepseek-v4-flash", harness="omp-cli"
        ),
    )


def _omp_request(*, effort: ReasoningEffort = ReasoningEffort.MAX) -> Any:
    return build_request(
        node_contract=_omp_node_contract(effort=effort),
        skill=_skill(),
        role_entry=_omp_role(),
        artifacts=(_artifact(),),
        selected_region="cn",
    )


# ===========================================================================
# Worker 02: ArtifactRef + DispatchReceipt contracts
# ===========================================================================


class TestArtifactRef:
    def test_valid_artifact_ref(self) -> None:
        ref = ArtifactRef(ref="seed", sha256=INPUT_ARTIFACT_SHA, snippet="hello")
        assert ref.ref == "seed"
        assert ref.sha256 == INPUT_ARTIFACT_SHA

    def test_empty_ref_fails_closed(self) -> None:
        with pytest.raises(HarnessPolicyError, match="ref name must be non-empty"):
            ArtifactRef(ref="  ", sha256=INPUT_ARTIFACT_SHA)

    def test_malformed_sha_fails_closed(self) -> None:
        with pytest.raises(HarnessPolicyError, match="64-char hex"):
            ArtifactRef(ref="seed", sha256="not-a-hash")

    def test_control_char_in_ref_fails_closed(self) -> None:
        with pytest.raises(HarnessPolicyError, match="whitespace control"):
            ArtifactRef(ref="see\td", sha256=INPUT_ARTIFACT_SHA)

    def test_oversized_snippet_fails_closed(self) -> None:
        with pytest.raises(HarnessPolicyError, match="8192-char"):
            ArtifactRef(ref="seed", sha256=INPUT_ARTIFACT_SHA, snippet="x" * 8193)

    def test_absolute_path_ref_fails_closed(self) -> None:
        with pytest.raises(HarnessPolicyError, match="logical"):
            ArtifactRef(ref="/etc/passwd", sha256=INPUT_ARTIFACT_SHA)

    def test_home_path_ref_fails_closed(self) -> None:
        with pytest.raises(HarnessPolicyError, match="logical"):
            ArtifactRef(ref="~/secret", sha256=INPUT_ARTIFACT_SHA)

    def test_traversal_ref_fails_closed(self) -> None:
        with pytest.raises(HarnessPolicyError, match="logical"):
            ArtifactRef(ref="../escape", sha256=INPUT_ARTIFACT_SHA)

    def test_uppercase_ref_fails_closed(self) -> None:
        with pytest.raises(HarnessPolicyError, match="logical"):
            ArtifactRef(ref="Seed", sha256=INPUT_ARTIFACT_SHA)

    def test_namespaced_ref_accepted(self) -> None:
        ref = ArtifactRef(ref="chapter-1/draft", sha256=INPUT_ARTIFACT_SHA)
        assert ref.ref == "chapter-1/draft"


class TestDispatchReceipt:
    def test_valid_receipt(self) -> None:
        receipt = DispatchReceipt(
            provider_session_id="sess-1",
            output_sha256=OUTPUT_SHA,
            observed_provider="deepseek",
            observed_model="deepseek-v4-flash",
            output_artifact_ref="chapter-1-draft",
            output_schema_ref=OUTPUT_SCHEMA,
        )
        assert receipt.output_sha256 == OUTPUT_SHA
        assert receipt.output_artifact_ref == "chapter-1-draft"

    def test_empty_session_fails_closed(self) -> None:
        with pytest.raises(HarnessPolicyError, match="provider_session_id"):
            DispatchReceipt(
                provider_session_id="  ",
                output_sha256=OUTPUT_SHA,
                observed_provider="deepseek",
                observed_model="m",
                output_artifact_ref="out",
                output_schema_ref=OUTPUT_SCHEMA,
            )

    def test_malformed_output_sha_fails_closed(self) -> None:
        with pytest.raises(HarnessPolicyError, match="64-char hex"):
            DispatchReceipt(
                provider_session_id="sess-1",
                output_sha256="bad",
                observed_provider="deepseek",
                observed_model="m",
                output_artifact_ref="out",
                output_schema_ref=OUTPUT_SCHEMA,
            )

    def test_empty_output_artifact_ref_fails_closed(self) -> None:
        with pytest.raises(HarnessPolicyError, match="output_artifact_ref"):
            DispatchReceipt(
                provider_session_id="sess-1",
                output_sha256=OUTPUT_SHA,
                observed_provider="deepseek",
                observed_model="m",
                output_artifact_ref="",
                output_schema_ref=OUTPUT_SCHEMA,
            )

    def test_empty_output_schema_ref_fails_closed(self) -> None:
        with pytest.raises(HarnessPolicyError, match="output_schema_ref"):
            DispatchReceipt(
                provider_session_id="sess-1",
                output_sha256=OUTPUT_SHA,
                observed_provider="deepseek",
                observed_model="m",
                output_artifact_ref="out",
                output_schema_ref="",
            )


# ===========================================================================
# Worker 02: build_request policy validation
# ===========================================================================


class TestBuildRequestPolicy:
    def test_valid_request_builds(self) -> None:
        request = _build_llm_request()
        assert request.role == "product-llm"
        assert request.provider == "deepseek"
        assert request.reasoning_effort is ReasoningEffort.MAX
        assert request.selected_region == "cn"
        assert request.prompt_sha256 == PROMPT_SHA

    def test_role_id_mismatch_fails_closed(self) -> None:
        with pytest.raises(
            HarnessPolicyError, match="does not match registered role_id"
        ):
            build_request(
                node_contract=_node_contract(role="wrong-role"),
                skill=_skill(),
                role_entry=_llm_role(),
                artifacts=(_artifact(),),
                selected_region="cn",
            )

    def test_provider_mismatch_with_role_target_fails_closed(self) -> None:
        # NodeExecutionContract validates provider-in-allowlist at construction,
        # so tamper after building a valid contract.
        contract = _node_contract()
        object.__setattr__(contract, "provider", "rogue")
        with pytest.raises(HarnessPolicyError, match="target-profile provider"):
            build_request(
                node_contract=contract,
                skill=_skill(),
                role_entry=_llm_role(),
                artifacts=(_artifact(),),
                selected_region="cn",
            )

    def test_model_mismatch_with_role_target_fails_closed(self) -> None:
        contract = _node_contract()
        object.__setattr__(contract, "model", "rogue-model")
        with pytest.raises(HarnessPolicyError, match="target-profile model"):
            build_request(
                node_contract=contract,
                skill=_skill(),
                role_entry=_llm_role(),
                artifacts=(_artifact(),),
                selected_region="cn",
            )

    def test_thinking_frozen_role_with_effort_fails_closed(self) -> None:
        with pytest.raises(HarnessPolicyError, match="thinking-frozen|allowed_efforts"):
            build_request(
                node_contract=_node_contract(
                    role="product-ocr",
                    provider="paddle-official",
                    model="PaddleOCR-VL-1.6",
                    effort=ReasoningEffort.LOW,
                    allowed_providers=("paddle-official",),
                ),
                skill=_skill(),
                role_entry=_ocr_role(),
                artifacts=(_artifact(),),
                selected_region="cn",
            )

    def test_skill_id_mismatch_fails_closed(self) -> None:
        with pytest.raises(HarnessPolicyError, match="skill_definition_id"):
            build_request(
                node_contract=_node_contract(skill_id="wrong-skill"),
                skill=_skill(),
                role_entry=_llm_role(),
                artifacts=(_artifact(),),
                selected_region="cn",
            )

    def test_input_schema_mismatch_fails_closed(self) -> None:
        contract = _node_contract()
        object.__setattr__(contract, "input_schema_ref", "https://wrong/x.json")
        with pytest.raises(HarnessPolicyError, match="input_schema_ref"):
            build_request(
                node_contract=contract,
                skill=_skill(),
                role_entry=_llm_role(),
                artifacts=(_artifact(),),
                selected_region="cn",
            )

    def test_output_schema_mismatch_fails_closed(self) -> None:
        contract = _node_contract()
        object.__setattr__(contract, "output_schema_ref", "https://wrong/x.json")
        with pytest.raises(HarnessPolicyError, match="output_schema_ref"):
            build_request(
                node_contract=contract,
                skill=_skill(),
                role_entry=_llm_role(),
                artifacts=(_artifact(),),
                selected_region="cn",
            )

    def test_artifact_hash_substitution_fails_closed(self) -> None:
        wrong_sha = "d" * 64
        with pytest.raises(HarnessPolicyError, match="hash tuple does not match"):
            build_request(
                node_contract=_node_contract(),
                skill=_skill(),
                role_entry=_llm_role(),
                artifacts=(_artifact(sha=wrong_sha),),
                selected_region="cn",
            )

    def test_artifact_hash_omission_fails_closed(self) -> None:
        with pytest.raises(HarnessPolicyError, match="hash tuple does not match"):
            build_request(
                node_contract=_node_contract(
                    input_hashes=(INPUT_ARTIFACT_SHA, "d" * 64)
                ),
                skill=_skill(),
                role_entry=_llm_role(),
                artifacts=(_artifact(),),
                selected_region="cn",
            )

    def test_contract_tool_outside_skill_fails_closed(self) -> None:
        with pytest.raises(HarnessPolicyError, match="outside the skill's closed set"):
            build_request(
                node_contract=_node_contract(allowed_tools=("rogue-tool",)),
                skill=_skill(allowed_tools=("deepseek-chat",)),
                role_entry=_llm_role(),
                artifacts=(_artifact(),),
                selected_region="cn",
            )

    def test_empty_skill_tools_rejects_contract_tools(self) -> None:
        with pytest.raises(HarnessPolicyError, match="outside the skill's closed set"):
            build_request(
                node_contract=_node_contract(allowed_tools=("any-tool",)),
                skill=_skill(allowed_tools=()),
                role_entry=_llm_role(),
                artifacts=(_artifact(),),
                selected_region="cn",
            )

    def test_credential_in_snippet_fails_closed(self) -> None:
        with pytest.raises(HarnessPolicyError, match="credential-shaped"):
            build_request(
                node_contract=_node_contract(),
                skill=_skill(),
                role_entry=_llm_role(),
                artifacts=(_artifact(snippet="api_key=sk-" + "a" * 30),),
                selected_region="cn",
            )

    def test_selected_region_required(self) -> None:
        with pytest.raises(HarnessPolicyError, match="selected target region"):
            build_request(
                node_contract=_node_contract(),
                skill=_skill(),
                role_entry=_llm_role(),
                artifacts=(_artifact(),),
                selected_region="",
            )

    def test_selected_region_outside_node_allowlist_fails_closed(self) -> None:
        with pytest.raises(HarnessPolicyError, match="outside the node contract"):
            build_request(
                node_contract=_node_contract(),
                skill=_skill(),
                role_entry=_llm_role(),
                artifacts=(_artifact(),),
                selected_region="unlisted",
            )

    def test_selected_region_outside_role_regions_fails_closed(self) -> None:
        role = _role_entry(
            target=_target_profile(regions=("cn",)),
        )
        contract = _node_contract(allowed_regions=("cn", "us"))
        with pytest.raises(HarnessPolicyError, match="outside the role target-profile"):
            build_request(
                node_contract=contract,
                skill=_skill(),
                role_entry=role,
                artifacts=(_artifact(),),
                selected_region="us",
            )

    def test_request_sensitivity_exceeds_role_ceiling_fails_closed(self) -> None:
        role = _role_entry(
            target=_target_profile(sensitivity="internal"),
        )
        with pytest.raises(
            HarnessPolicyError, match="exceeds the role target-profile ceiling"
        ):
            build_request(
                node_contract=_node_contract(sensitivity=SensitivityTier.CONFIDENTIAL),
                skill=_skill(),
                role_entry=role,
                artifacts=(_artifact(),),
                selected_region="cn",
            )

    def test_request_payload_is_credential_free(self) -> None:
        request = _build_llm_request()
        payload = request.to_payload()
        assert "password" not in str(payload).lower()
        assert payload["role"] == "product-llm"
        assert payload["prompt_sha256"] == PROMPT_SHA
        assert payload["selected_region"] == "cn"
        assert payload["allowed_tools"] == ["deepseek-chat"]
        assert payload["allowed_paths"] == ["artifacts/chapter-draft/"]

    def test_provider_session_id_carried_into_request(self) -> None:
        request = build_request(
            node_contract=_node_contract(provider_session_id="sess-recover-1"),
            skill=_skill(),
            role_entry=_llm_role(),
            artifacts=(_artifact(),),
            selected_region="cn",
        )
        assert request.provider_session_id == "sess-recover-1"
        assert request.same_session_recovery is True

    def test_session_id_rejected_when_recovery_is_not_authorized(self) -> None:
        with pytest.raises(HarnessPolicyError, match="same_session_recovery is false"):
            build_request(
                node_contract=_node_contract(
                    provider_session_id="sess-not-authorized",
                    same_session_recovery=False,
                ),
                skill=_skill(),
                role_entry=_llm_role(),
                artifacts=(_artifact(),),
                selected_region="cn",
            )

    def test_request_payload_carries_recovery_authority(self) -> None:
        request = _build_llm_request()
        assert request.to_payload()["same_session_recovery"] is True


# ===========================================================================
# Worker 02: ProbePolicy
# ===========================================================================


class TestProbePolicy:
    def test_first_use_probe_succeeds_then_cached(self) -> None:
        policy = ProbePolicy()
        adapter = _direct_adapter()
        policy.ensure_probed(adapter)
        policy.ensure_probed(adapter)

    def test_failed_probe_raises_and_is_cached(self) -> None:
        policy = ProbePolicy()
        fake = _FakeDirectApi(probe_ok=False)
        adapter = DirectApiAdapter(
            provider="deepseek",
            model="deepseek-v4-flash",
            dispatch_fn=fake,
            probe_fn=fake.probe,
        )
        with pytest.raises(AdapterProbeError, match="returned False"):
            policy.ensure_probed(adapter)
        with pytest.raises(AdapterProbeError, match="cached failed probe"):
            policy.ensure_probed(adapter)

    def test_probe_raising_is_cached_as_failure(self) -> None:
        policy = ProbePolicy()

        def raising_probe() -> bool:
            raise ConnectionError("boom")

        adapter = DirectApiAdapter(
            provider="deepseek",
            model="deepseek-v4-flash",
            dispatch_fn=_FakeDirectApi(),
            probe_fn=raising_probe,
        )
        with pytest.raises(AdapterProbeError, match="raised"):
            policy.ensure_probed(adapter)
        with pytest.raises(AdapterProbeError, match="cached failed probe"):
            policy.ensure_probed(adapter)

    def test_clear_removes_cached_failure(self) -> None:
        policy = ProbePolicy()
        fake = _FakeDirectApi(probe_ok=False)
        adapter = DirectApiAdapter(
            provider="deepseek",
            model="deepseek-v4-flash",
            dispatch_fn=fake,
            probe_fn=fake.probe,
        )
        with pytest.raises(AdapterProbeError):
            policy.ensure_probed(adapter)
        fake.probe_ok = True
        policy.clear(adapter.identity)
        policy.ensure_probed(adapter)


# ===========================================================================
# Worker 02: Direct API dispatch
# ===========================================================================


class TestDirectApiDispatch:
    def test_valid_dispatch_produces_typed_receipt(self) -> None:
        fake = _FakeDirectApi()
        adapter = DirectApiAdapter(
            provider="deepseek",
            model="deepseek-v4-flash",
            dispatch_fn=fake,
            probe_fn=fake.probe,
        )
        result = HarnessDispatcher().dispatch(
            request=_build_llm_request(), adapter=adapter
        )
        assert result.success is True
        assert result.dispatched is True
        assert result.receipt is not None
        assert result.receipt.observed_provider == "deepseek"
        assert result.receipt.output_artifact_ref == "chapter-1-draft"
        assert result.receipt.output_schema_ref == OUTPUT_SCHEMA
        assert fake.invocations == 1

    def test_probe_failure_prevents_dispatch(self) -> None:
        fake = _FakeDirectApi(probe_ok=False)
        adapter = DirectApiAdapter(
            provider="deepseek",
            model="deepseek-v4-flash",
            dispatch_fn=fake,
            probe_fn=fake.probe,
        )
        result = HarnessDispatcher().dispatch(
            request=_build_llm_request(), adapter=adapter
        )
        assert result.success is False
        assert result.dispatched is False
        assert result.error_code == "probe_failed"
        assert fake.invocations == 0

    def test_preflight_mismatch_prevents_dispatch(self) -> None:
        fake = _FakeDirectApi()
        adapter = DirectApiAdapter(
            provider="wrong",
            model="deepseek-v4-flash",
            dispatch_fn=fake,
            probe_fn=fake.probe,
        )
        request = _build_llm_request()
        result = HarnessDispatcher().dispatch(request=request, adapter=adapter)
        assert result.success is False
        assert result.dispatched is False
        assert "mismatch" in (result.error_code or "")
        assert fake.invocations == 0

    def test_dispatch_exception_returns_failed_result(self) -> None:
        def raising_fn(payload: dict[str, Any]) -> dict[str, Any]:
            raise RuntimeError("provider down")

        adapter = DirectApiAdapter(
            provider="deepseek",
            model="deepseek-v4-flash",
            dispatch_fn=raising_fn,
            probe_fn=lambda: True,
        )
        result = HarnessDispatcher().dispatch(
            request=_build_llm_request(), adapter=adapter
        )
        assert result.success is False
        assert result.dispatched is True
        assert result.error_code == "dispatch_exception"

    def test_receipt_schema_mismatch_fails_closed(self) -> None:
        fake = _FakeDirectApi(
            receipt={
                "provider_session_id": "s",
                "output_sha256": OUTPUT_SHA,
                "observed_provider": "deepseek",
                "observed_model": "deepseek-v4-flash",
                "output_artifact_ref": "out",
                "output_schema_ref": "https://wrong/schema.json",
            }
        )
        adapter = DirectApiAdapter(
            provider="deepseek",
            model="deepseek-v4-flash",
            dispatch_fn=fake,
            probe_fn=fake.probe,
        )
        result = HarnessDispatcher().dispatch(
            request=_build_llm_request(), adapter=adapter
        )
        assert result.success is False
        assert result.error_code == "receipt_schema_mismatch"


# ===========================================================================
# Worker 02: Unified workload gate (OCR + translation)
# ===========================================================================


def _translation_request() -> Any:
    return build_request(
        node_contract=_node_contract(
            role="product-translation",
            harness="local-omlx",
            provider="local-omlx",
            model="dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX",
            effort=ReasoningEffort.NONE,
            allowed_providers=("local-omlx",),
            allowed_regions=("local",),
        ),
        skill=_skill(),
        role_entry=_translation_role(),
        artifacts=(_artifact(),),
        selected_region="local",
    )


def _ocr_request(model: str = "PaddleOCR-VL-1.6") -> Any:
    return build_request(
        node_contract=_node_contract(
            role="product-ocr",
            harness="direct-api",
            provider="paddle-official",
            model=model,
            effort=ReasoningEffort.NONE,
            allowed_providers=("paddle-official",),
            allowed_regions=("cn",),
        ),
        skill=_skill(),
        role_entry=_ocr_role(),
        artifacts=(_artifact(),),
        selected_region="cn",
    )


class TestUnifiedWorkloadGate:
    def test_translation_succeeds_when_gate_matches(self) -> None:
        gate = _FakeOmlxGate(
            gate_selection={
                "models": {"translation": "dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX"}
            }
        )
        dispatch_fake = _FakeOmlxDispatch()
        adapter = LocalOmlxAdapter(
            provider="local-omlx",
            model="dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX",
            dispatch_fn=dispatch_fake,
            probe_fn=dispatch_fake.probe,
        )
        result = HarnessDispatcher().dispatch(
            request=_translation_request(),
            adapter=adapter,
            gate_selection=gate.gate_selection,
            lease_factory=gate.lease,
        )
        assert result.success is True
        assert len(gate.acquired) == 1
        assert len(gate.released) == 1
        assert gate.acquired[0][0] == "translation"
        assert dispatch_fake.invocations == 1

    def test_paddle_ocr_fails_closed_when_gate_selects_glm(self) -> None:
        """The registered Paddle OCR harness is Direct API, but the unified
        gate policy catches the GLM-vs-Paddle mismatch at the common boundary."""
        gate = _FakeOmlxGate(gate_selection={"models": {"ocr": "GLM-OCR-bf16"}})
        fake = _FakeDirectApi(
            receipt={
                "provider_session_id": "s",
                "output_sha256": OUTPUT_SHA,
                "observed_provider": "paddle-official",
                "observed_model": "PaddleOCR-VL-1.6",
                "output_artifact_ref": "ocr-out",
                "output_schema_ref": OUTPUT_SCHEMA,
            }
        )
        adapter = DirectApiAdapter(
            provider="paddle-official",
            model="PaddleOCR-VL-1.6",
            dispatch_fn=fake,
            probe_fn=fake.probe,
        )
        result = HarnessDispatcher().dispatch(
            request=_ocr_request(),
            adapter=adapter,
            gate_selection=gate.gate_selection,
            lease_factory=gate.lease,
        )
        assert result.success is False
        assert result.dispatched is False
        assert result.error_code == "gate_policy_violation"
        assert fake.invocations == 0
        assert len(gate.acquired) == 0

    def test_ocr_role_with_no_gate_model_fails_closed(self) -> None:
        gate = _FakeOmlxGate(gate_selection={})
        fake = _FakeDirectApi()
        adapter = DirectApiAdapter(
            provider="paddle-official",
            model="PaddleOCR-VL-1.6",
            dispatch_fn=fake,
            probe_fn=fake.probe,
        )
        result = HarnessDispatcher().dispatch(
            request=_ocr_request(),
            adapter=adapter,
            gate_selection=gate.gate_selection,
            lease_factory=gate.lease,
        )
        assert result.success is False
        assert result.error_code == "gate_policy_violation"
        assert fake.invocations == 0

    def test_ocr_succeeds_when_gate_matches(self) -> None:
        gate = _FakeOmlxGate(gate_selection={"models": {"ocr": "PaddleOCR-VL-1.6"}})
        fake = _FakeDirectApi(
            receipt={
                "provider_session_id": "s",
                "output_sha256": OUTPUT_SHA,
                "observed_provider": "paddle-official",
                "observed_model": "PaddleOCR-VL-1.6",
                "output_artifact_ref": "ocr-out",
                "output_schema_ref": OUTPUT_SCHEMA,
            }
        )
        adapter = DirectApiAdapter(
            provider="paddle-official",
            model="PaddleOCR-VL-1.6",
            dispatch_fn=fake,
            probe_fn=fake.probe,
        )
        result = HarnessDispatcher().dispatch(
            request=_ocr_request(),
            adapter=adapter,
            gate_selection=gate.gate_selection,
            lease_factory=gate.lease,
        )
        assert result.success is True
        assert fake.invocations == 1
        assert gate.acquired[0][0] == "ocr"

    def test_gate_model_identity_is_case_sensitive(self) -> None:
        gate = _FakeOmlxGate(gate_selection={"models": {"ocr": "paddleocr-vl-1.6"}})
        fake = _FakeDirectApi()
        adapter = DirectApiAdapter(
            provider="paddle-official",
            model="PaddleOCR-VL-1.6",
            dispatch_fn=fake,
            probe_fn=fake.probe,
        )
        result = HarnessDispatcher().dispatch(
            request=_ocr_request(),
            adapter=adapter,
            gate_selection=gate.gate_selection,
            lease_factory=gate.lease,
        )
        assert result.success is False
        assert result.error_code == "gate_policy_violation"
        assert result.dispatched is False
        assert fake.invocations == 0

    def test_gate_model_identity_rejects_surrounding_whitespace(self) -> None:
        gate = _FakeOmlxGate(gate_selection={"models": {"ocr": "PaddleOCR-VL-1.6 "}})
        fake = _FakeDirectApi()
        adapter = DirectApiAdapter(
            provider="paddle-official",
            model="PaddleOCR-VL-1.6",
            dispatch_fn=fake,
            probe_fn=fake.probe,
        )
        result = HarnessDispatcher().dispatch(
            request=_ocr_request(),
            adapter=adapter,
            gate_selection=gate.gate_selection,
            lease_factory=gate.lease,
        )
        assert result.error_code == "gate_policy_violation"
        assert result.dispatched is False
        assert fake.invocations == 0

    def test_gate_required_for_translation_role(self) -> None:
        fake = _FakeOmlxDispatch()
        adapter = LocalOmlxAdapter(
            provider="local-omlx",
            model="dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX",
            dispatch_fn=fake,
            probe_fn=fake.probe,
        )
        result = HarnessDispatcher().dispatch(
            request=_translation_request(), adapter=adapter
        )
        assert result.success is False
        assert result.error_code == "gate_policy_violation"
        assert fake.invocations == 0

    def test_lease_factory_required_for_ocr_role(self) -> None:
        fake = _FakeDirectApi()
        adapter = DirectApiAdapter(
            provider="paddle-official",
            model="PaddleOCR-VL-1.6",
            dispatch_fn=fake,
            probe_fn=fake.probe,
        )
        result = HarnessDispatcher().dispatch(
            request=_ocr_request(),
            adapter=adapter,
            gate_selection={"models": {"ocr": "PaddleOCR-VL-1.6"}},
            # Missing lease_factory.
        )
        assert result.success is False
        assert result.error_code == "gate_policy_violation"

    def test_lease_released_even_on_dispatch_exception(self) -> None:
        gate = _FakeOmlxGate(
            gate_selection={
                "models": {"translation": "dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX"}
            }
        )

        def raising_fn(
            payload: dict[str, Any], lease: Mapping[str, Any]
        ) -> dict[str, Any]:
            raise RuntimeError("omlx crashed")

        adapter = LocalOmlxAdapter(
            provider="local-omlx",
            model="dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX",
            dispatch_fn=raising_fn,
            probe_fn=lambda: True,
        )
        result = HarnessDispatcher().dispatch(
            request=_translation_request(),
            adapter=adapter,
            gate_selection=gate.gate_selection,
            lease_factory=gate.lease,
        )
        assert result.success is False
        assert result.error_code == "dispatch_exception"
        assert len(gate.acquired) == 1
        assert len(gate.released) == 1

    def test_lease_release_failure_is_typed_after_completed_transport(self) -> None:
        class ReleaseFailingLease:
            def __enter__(self) -> Mapping[str, Any]:
                return {"lease_id": "lease-release-fails"}

            def __exit__(self, *args: object) -> None:
                raise RuntimeError("release failed")

        fake = _FakeOmlxDispatch()
        adapter = LocalOmlxAdapter(
            provider="local-omlx",
            model="dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX",
            dispatch_fn=fake,
            probe_fn=fake.probe,
        )
        result = HarnessDispatcher().dispatch(
            request=_translation_request(),
            adapter=adapter,
            gate_selection={
                "models": {"translation": "dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX"}
            },
            lease_factory=lambda **_: ReleaseFailingLease(),
        )
        assert result.success is False
        assert result.error_code == "gate_lease_release_failed"
        assert result.dispatched is True
        assert result.receipt is None
        assert fake.invocations == 1

    def test_dispatch_failure_is_not_masked_when_lease_release_also_fails(self) -> None:
        class ReleaseFailingLease:
            def __enter__(self) -> Mapping[str, Any]:
                return {"lease_id": "lease-release-fails"}

            def __exit__(self, *args: object) -> None:
                raise RuntimeError("release failed")

        def raising_fn(
            payload: dict[str, Any], lease: Mapping[str, Any]
        ) -> dict[str, Any]:
            raise RuntimeError("transport failed")

        adapter = LocalOmlxAdapter(
            provider="local-omlx",
            model="dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX",
            dispatch_fn=raising_fn,
            probe_fn=lambda: True,
        )
        result = HarnessDispatcher().dispatch(
            request=_translation_request(),
            adapter=adapter,
            gate_selection={
                "models": {"translation": "dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX"}
            },
            lease_factory=lambda **_: ReleaseFailingLease(),
        )
        assert result.success is False
        assert result.error_code == "dispatch_exception"
        assert result.dispatched is True
        assert "transport failed" in (result.error_message or "")
        assert "lease release also failed" in (result.error_message or "")

    def test_lease_acquisition_failure_dispatched_false(self) -> None:
        gate = _FakeOmlxGate(
            gate_selection={
                "models": {"translation": "dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX"}
            }
        )
        fake = _FakeOmlxDispatch()

        @contextmanager
        def failing_lease(**kwargs: Any) -> Iterator[Mapping[str, Any]]:
            raise RuntimeError("gate acquisition failed")
            yield {}  # never reached  # pragma: no cover

        adapter = LocalOmlxAdapter(
            provider="local-omlx",
            model="dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX",
            dispatch_fn=fake,
            probe_fn=fake.probe,
        )
        result = HarnessDispatcher().dispatch(
            request=_translation_request(),
            adapter=adapter,
            gate_selection=gate.gate_selection,
            lease_factory=failing_lease,
        )
        assert result.success is False
        assert result.dispatched is False
        assert result.error_code == "gate_lease_acquisition_failed"
        assert fake.invocations == 0

    def test_llm_role_does_not_require_gate(self) -> None:
        fake = _FakeDirectApi()
        adapter = DirectApiAdapter(
            provider="deepseek",
            model="deepseek-v4-flash",
            dispatch_fn=fake,
            probe_fn=fake.probe,
        )
        result = HarnessDispatcher().dispatch(
            request=_build_llm_request(), adapter=adapter
        )
        assert result.success is True
        assert fake.invocations == 1

    def test_workload_gate_error_is_policy_error(self) -> None:
        assert issubclass(WorkloadGateError, HarnessPolicyError)


# ===========================================================================
# Worker 02: Fallback
# ===========================================================================


class TestFallback:
    def test_valid_fallback_rebuilds_from_canonical_source_only(self) -> None:
        fallback = FallbackInput(
            logical_call_id="lc:1",
            idempotency_key="idem-1",
            sensitivity_tier=SensitivityTier.CONFIDENTIAL,
            allowed_providers=("deepseek",),
            allowed_regions=("cn",),
            canonical_source={"content": "canonical material"},
            target_provider="deepseek",
            target_region="cn",
            previous_terminal_state="failed",
            previous_error_code="dispatch_exception",
            **_prior_fallback_evidence({"content": "canonical material"}),
            previous_provider_scratchpad={"secret": "leak"},
            session_transcript=[{"turn": 1}],
            raw_sensitive_payload={"raw": "data"},
        )
        payload = build_fallback_request(fallback)
        assert payload["content"] == "canonical material"
        assert "previous_provider_scratchpad" not in payload
        assert "session_transcript" not in payload
        assert "raw_sensitive_payload" not in payload

    def test_fallback_without_eligible_terminal_state_fails_closed(self) -> None:
        with pytest.raises(HarnessFallbackError, match="eligible terminal"):
            build_fallback_request(
                FallbackInput(
                    logical_call_id="lc:1",
                    idempotency_key="idem-1",
                    sensitivity_tier=SensitivityTier.PUBLIC,
                    allowed_providers=("deepseek",),
                    allowed_regions=("cn",),
                    canonical_source={"content": "x"},
                    previous_terminal_state="completed",
                    previous_error_code="",
                )
            )

    def test_fallback_without_error_code_fails_closed(self) -> None:
        with pytest.raises(HarnessFallbackError, match="error code"):
            build_fallback_request(
                FallbackInput(
                    logical_call_id="lc:1",
                    idempotency_key="idem-1",
                    sensitivity_tier=SensitivityTier.PUBLIC,
                    allowed_providers=("deepseek",),
                    allowed_regions=("cn",),
                    canonical_source={"content": "x"},
                    previous_terminal_state="unavailable",
                    previous_error_code="  ",
                )
            )

    def test_fallback_restricted_without_target_fails_closed(self) -> None:
        with pytest.raises(HarnessFallbackError, match="restricted"):
            build_fallback_request(
                FallbackInput(
                    logical_call_id="lc:1",
                    idempotency_key="idem-1",
                    sensitivity_tier=SensitivityTier.RESTRICTED,
                    allowed_providers=("deepseek",),
                    allowed_regions=("cn",),
                    canonical_source={"content": "x"},
                    previous_terminal_state="failed",
                    previous_error_code="dispatch_exception",
                    **_prior_fallback_evidence({"content": "x"}),
                )
            )

    def test_fallback_credential_in_rebuilt_payload_fails_closed(self) -> None:
        with pytest.raises(HarnessPolicyError, match="credential-shaped"):
            build_fallback_request(
                FallbackInput(
                    logical_call_id="lc:1",
                    idempotency_key="idem-1",
                    sensitivity_tier=SensitivityTier.PUBLIC,
                    allowed_providers=("deepseek",),
                    allowed_regions=("cn",),
                    canonical_source={"api_key": "sk-" + "a" * 30},
                    previous_terminal_state="failed",
                    previous_error_code="dispatch_exception",
                    **_prior_fallback_evidence({"api_key": "sk-" + "a" * 30}),
                )
            )

    def test_fallback_prior_identity_must_match(self) -> None:
        with pytest.raises(HarnessFallbackError, match="logical_call_id"):
            build_fallback_request(
                FallbackInput(
                    logical_call_id="lc:1",
                    idempotency_key="idem-1",
                    sensitivity_tier=SensitivityTier.PUBLIC,
                    allowed_providers=("deepseek",),
                    allowed_regions=("cn",),
                    canonical_source={"content": "x"},
                    previous_terminal_state="failed",
                    previous_error_code="dispatch_exception",
                    **_prior_fallback_evidence(
                        {"content": "x"}, logical_call_id="lc:different"
                    ),
                )
            )

    def test_fallback_prior_input_hash_must_match(self) -> None:
        evidence = _prior_fallback_evidence({"content": "different"})
        with pytest.raises(HarnessFallbackError, match="input hash"):
            build_fallback_request(
                FallbackInput(
                    logical_call_id="lc:1",
                    idempotency_key="idem-1",
                    sensitivity_tier=SensitivityTier.PUBLIC,
                    allowed_providers=("deepseek",),
                    allowed_regions=("cn",),
                    canonical_source={"content": "x"},
                    previous_terminal_state="failed",
                    previous_error_code="dispatch_exception",
                    **evidence,
                )
            )


# ===========================================================================
# Worker 02: No-duplicate-dispatch
# ===========================================================================


class TestNoDuplicateDispatch:
    def test_request_class_exposes_no_validation_stamp_factory(self) -> None:
        assert not hasattr(HarnessDispatchRequest, "_validated_construct")

        import app.protocol_workflow.runtime.harness as harness_module

        assert not hasattr(harness_module, "_seal_validated_request")
        assert build_request.__closure__ is None

    def test_altered_validated_request_fails_revalidation(self) -> None:
        request = _build_llm_request()
        fake = _FakeDirectApi()
        object.__setattr__(request, "allowed_tools", ("not-in-skill",))

        result = HarnessDispatcher().dispatch(
            request=request, adapter=_direct_adapter(fake)
        )

        assert result.success is False
        assert result.error_code == "request_unvalidated"
        assert result.dispatched is False
        assert fake.probe_calls == 0
        assert fake.invocations == 0

    def test_altered_non_payload_binding_metadata_fails_revalidation(self) -> None:
        request = _build_llm_request()
        fake = _FakeDirectApi()
        assert request._binding_evidence is not None
        object.__setattr__(request._binding_evidence.skill, "skill_version", "9.9.9")

        result = HarnessDispatcher().dispatch(
            request=request, adapter=_direct_adapter(fake)
        )

        assert result.error_code == "request_unvalidated"
        assert result.dispatched is False
        assert fake.probe_calls == 0
        assert fake.invocations == 0

    def test_policy_failure_produces_zero_dispatches(self) -> None:
        fake = _FakeDirectApi()
        with pytest.raises(HarnessPolicyError):
            build_request(
                node_contract=_node_contract(),
                skill=_skill(),
                role_entry=_llm_role(),
                artifacts=(_artifact(snippet="api_key=sk-" + "a" * 30),),
                selected_region="cn",
            )
        assert fake.invocations == 0

    def test_probe_failure_does_not_clear_on_retry(self) -> None:
        fake = _FakeDirectApi(probe_ok=False)
        adapter = DirectApiAdapter(
            provider="deepseek",
            model="deepseek-v4-flash",
            dispatch_fn=fake,
            probe_fn=fake.probe,
        )
        dispatcher = HarnessDispatcher()
        r1 = dispatcher.dispatch(request=_build_llm_request(), adapter=adapter)
        r2 = dispatcher.dispatch(request=_build_llm_request(), adapter=adapter)
        assert r1.success is False
        assert r2.success is False
        assert r1.error_code == "probe_failed"
        assert r2.error_code == "probe_failed"
        assert fake.invocations == 0


# ===========================================================================
# Worker 02: Typed receipt identity
# ===========================================================================


class TestReceiptIdentity:
    def test_direct_api_receipt_carries_observed_identity(self) -> None:
        fake = _FakeDirectApi(
            receipt={
                "provider_session_id": "sess-42",
                "output_sha256": _sha("output"),
                "observed_provider": "deepseek",
                "observed_model": "deepseek-v4-flash",
                "output_artifact_ref": "out-1",
                "output_schema_ref": OUTPUT_SCHEMA,
            }
        )
        adapter = DirectApiAdapter(
            provider="deepseek",
            model="deepseek-v4-flash",
            dispatch_fn=fake,
            probe_fn=fake.probe,
        )
        result = HarnessDispatcher().dispatch(
            request=_build_llm_request(), adapter=adapter
        )
        assert result.success is True
        assert result.receipt is not None
        assert result.receipt.provider_session_id == "sess-42"
        assert result.receipt.observed_model == "deepseek-v4-flash"
        assert result.receipt.output_artifact_ref == "out-1"

    def test_non_typed_receipt_returns_stable_failure(self) -> None:
        class InvalidReceiptAdapter:
            identity = "direct-api:deepseek:deepseek-v4-flash"
            provider = "deepseek"
            model = "deepseek-v4-flash"
            harness = "direct-api"

            def preflight(self, request: Any) -> AdapterOutcome:
                return AdapterOutcome()

            def probe(self) -> bool:
                return True

            def dispatch(self, request: Any, **kwargs: Any) -> None:
                return None

        result = HarnessDispatcher().dispatch(
            request=_build_llm_request(), adapter=InvalidReceiptAdapter()
        )
        assert result.success is False
        assert result.error_code == "dispatch_invalid_receipt"
        assert result.dispatched is True
        assert result.receipt is None

    def test_omlx_receipt_carries_observed_identity(self) -> None:
        gate = _FakeOmlxGate(
            gate_selection={
                "models": {"translation": "dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX"}
            }
        )
        dispatch_fake = _FakeOmlxDispatch(
            receipt={
                "provider_session_id": "sess-omlx-9",
                "output_sha256": _sha("translated"),
                "observed_provider": "local-omlx",
                "observed_model": "dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX",
                "output_artifact_ref": "trans-out",
                "output_schema_ref": OUTPUT_SCHEMA,
            }
        )
        adapter = LocalOmlxAdapter(
            provider="local-omlx",
            model="dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX",
            dispatch_fn=dispatch_fake,
            probe_fn=dispatch_fake.probe,
        )
        result = HarnessDispatcher().dispatch(
            request=_translation_request(),
            adapter=adapter,
            gate_selection=gate.gate_selection,
            lease_factory=gate.lease,
        )
        assert result.success is True
        assert result.receipt is not None
        assert result.receipt.observed_model == "dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX"


# ===========================================================================
# Worker 03: Codex App/CLI adapter — command plan + dispatch
# ===========================================================================


class TestCodexCommandPlan:
    def test_plan_has_explicit_model(self) -> None:
        plan = build_codex_exec_plan(
            model="deepseek-v4-flash",
            output_schema_path="/tmp/schema.json",
        )
        assert "--model" in plan
        idx = plan.index("--model")
        assert plan[idx + 1] == "deepseek-v4-flash"

    def test_plan_has_output_schema(self) -> None:
        plan = build_codex_exec_plan(
            model="m",
            output_schema_path="/tmp/schema.json",
        )
        idx = plan.index("--output-schema")
        assert plan[idx + 1] == "/tmp/schema.json"

    def test_plan_has_json_flag(self) -> None:
        plan = build_codex_exec_plan(model="m", output_schema_path="/tmp/schema.json")
        assert "--json" in plan

    def test_plan_never_has_no_tools(self) -> None:
        plan = build_codex_exec_plan(model="m", output_schema_path="/tmp/schema.json")
        assert "--no-tools" not in plan

    def test_plan_never_has_max_turns_1(self) -> None:
        plan = build_codex_exec_plan(model="m", output_schema_path="/tmp/schema.json")
        assert "--max-turns" not in plan
        assert "--max-turns=1" not in plan

    def test_new_dispatch_has_no_resume(self) -> None:
        plan = build_codex_exec_plan(model="m", output_schema_path="/tmp/schema.json")
        assert "resume" not in plan

    def test_resume_dispatch_uses_exec_resume(self) -> None:
        plan = build_codex_exec_plan(
            model="m",
            output_schema_path="/tmp/schema.json",
            session_id="sess-99",
        )
        assert plan[0] == "exec"
        assert plan[1] == "resume"
        assert plan[2] == "sess-99"

    def test_empty_model_fails_closed(self) -> None:
        with pytest.raises(ValueError, match="model"):
            build_codex_exec_plan(model="  ", output_schema_path="/tmp/schema.json")

    def test_empty_schema_path_fails_closed(self) -> None:
        with pytest.raises(ValueError, match="output_schema_path"):
            build_codex_exec_plan(model="m", output_schema_path="  ")

    def test_schema_uri_is_rejected_by_pure_builder(self) -> None:
        with pytest.raises(ValueError, match="local file path"):
            build_codex_exec_plan(model="m", output_schema_path=OUTPUT_SCHEMA)


class TestCodexDispatch:
    def test_valid_dispatch_produces_typed_receipt(self) -> None:
        fake = _FakeCodexTransport()
        adapter = _codex_adapter(fake)
        result = HarnessDispatcher().dispatch(request=_codex_request(), adapter=adapter)
        assert result.success is True
        assert result.dispatched is True
        assert result.receipt is not None
        assert result.receipt.observed_provider == "codex-app"
        assert result.receipt.observed_model == "deepseek-v4-flash"
        assert result.receipt.output_sha256 == OUTPUT_SHA
        assert result.receipt.output_artifact_ref == "codex-out"
        assert fake.invocations == 1

    def test_probe_failure_prevents_dispatch(self) -> None:
        fake = _FakeCodexTransport()
        fake.probe_ok = False
        adapter = _codex_adapter(fake)
        result = HarnessDispatcher().dispatch(request=_codex_request(), adapter=adapter)
        assert result.success is False
        assert result.dispatched is False
        assert result.error_code == "probe_failed"
        assert fake.invocations == 0

    def test_preflight_provider_mismatch_before_probe(self) -> None:
        fake = _FakeCodexTransport()
        adapter = CodexAppAdapter(
            provider="wrong",
            model="deepseek-v4-flash",
            transport=fake,
            probe_fn=fake.probe,
            schema_path_resolver=_default_schema_resolver,
        )
        request = _codex_request()
        result = HarnessDispatcher().dispatch(request=request, adapter=adapter)
        assert result.success is False
        assert result.dispatched is False
        assert result.error_code == "adapter_provider_mismatch"
        assert fake.invocations == 0

    def test_preflight_model_mismatch_before_probe(self) -> None:
        fake = _FakeCodexTransport()
        adapter = CodexAppAdapter(
            provider="codex-app",
            model="wrong",
            transport=fake,
            probe_fn=fake.probe,
            schema_path_resolver=_default_schema_resolver,
        )
        request = _codex_request()
        result = HarnessDispatcher().dispatch(request=request, adapter=adapter)
        assert result.success is False
        assert result.dispatched is False
        assert result.error_code == "adapter_model_mismatch"
        assert fake.invocations == 0

    def test_six_field_receipt_enforced(self) -> None:
        fake = _FakeCodexTransport(
            receipt={
                "provider_session_id": "sess-1",
                "output_sha256": OUTPUT_SHA,
                "observed_provider": "codex-app",
                "observed_model": "deepseek-v4-flash",
                # Missing output_artifact_ref and output_schema_ref.
            }
        )
        adapter = _codex_adapter(fake)
        result = HarnessDispatcher().dispatch(request=_codex_request(), adapter=adapter)
        assert result.success is False
        assert result.dispatched is True
        assert result.error_code == "dispatch_exception"
        assert "missing" in (result.error_message or "").lower()


# ===========================================================================
# Worker 03: OMP CLI adapter — command plan + dispatch
# ===========================================================================


class TestOmpCommandPlan:
    def test_plan_has_provider_and_model(self) -> None:
        plan = build_omp_cli_plan(
            provider="omp-cli",
            model="deepseek-v4-flash",
            reasoning_effort="high",
        )
        assert "--provider" in plan
        idx = plan.index("--provider")
        assert plan[idx + 1] == "omp-cli"
        assert "--model" in plan

    def test_plan_has_thinking_value(self) -> None:
        plan = build_omp_cli_plan(
            provider="p",
            model="m",
            reasoning_effort="high",
        )
        idx = plan.index("--thinking")
        assert plan[idx + 1] == "high"

    def test_plan_has_non_interactive(self) -> None:
        plan = build_omp_cli_plan(provider="p", model="m", reasoning_effort="high")
        assert "-p" in plan

    def test_plan_has_auto_approve(self) -> None:
        plan = build_omp_cli_plan(provider="p", model="m", reasoning_effort="high")
        assert "--auto-approve" in plan

    def test_plan_never_has_no_tools(self) -> None:
        plan = build_omp_cli_plan(provider="p", model="m", reasoning_effort="high")
        assert "--no-tools" not in plan

    def test_plan_never_has_max_turns_1(self) -> None:
        plan = build_omp_cli_plan(provider="p", model="m", reasoning_effort="high")
        assert "--max-turns" not in plan

    def test_plan_has_long_max_time(self) -> None:
        plan = build_omp_cli_plan(provider="p", model="m", reasoning_effort="high")
        idx = plan.index("--max-time")
        assert int(plan[idx + 1]) >= 3600

    def test_new_dispatch_has_no_resume(self) -> None:
        plan = build_omp_cli_plan(provider="p", model="m", reasoning_effort="high")
        assert "--resume" not in plan

    def test_resume_dispatch_has_resume(self) -> None:
        plan = build_omp_cli_plan(
            provider="p",
            model="m",
            reasoning_effort="high",
            session_id="sess-7",
        )
        idx = plan.index("--resume")
        assert plan[idx + 1] == "sess-7"


class TestOmpDispatch:
    def test_valid_dispatch_produces_typed_receipt(self) -> None:
        fake = _FakeOmpTransport()
        adapter = _omp_adapter(fake)
        result = HarnessDispatcher().dispatch(request=_omp_request(), adapter=adapter)
        assert result.success is True
        assert result.dispatched is True
        assert result.receipt is not None
        assert result.receipt.observed_provider == "omp-cli"
        assert result.receipt.observed_model == "deepseek-v4-flash"
        assert result.receipt.output_artifact_ref == "omp-out"
        assert fake.invocations == 1

    def test_probe_failure_prevents_dispatch(self) -> None:
        fake = _FakeOmpTransport()
        fake.probe_ok = False
        adapter = _omp_adapter(fake)
        result = HarnessDispatcher().dispatch(request=_omp_request(), adapter=adapter)
        assert result.success is False
        assert result.dispatched is False
        assert result.error_code == "probe_failed"
        assert fake.invocations == 0

    def test_preflight_provider_mismatch_before_probe(self) -> None:
        fake = _FakeOmpTransport()
        adapter = OmpCliAdapter(
            provider="wrong",
            model="deepseek-v4-flash",
            transport=fake,
            probe_fn=fake.probe,
        )
        request = _omp_request()
        result = HarnessDispatcher().dispatch(request=request, adapter=adapter)
        assert result.success is False
        assert result.dispatched is False
        assert result.error_code == "adapter_provider_mismatch"
        assert fake.invocations == 0

    def test_six_field_receipt_enforced(self) -> None:
        fake = _FakeOmpTransport(
            receipt={
                "provider_session_id": "sess-1",
                "output_sha256": OUTPUT_SHA,
                "observed_provider": "omp-cli",
                "observed_model": "deepseek-v4-flash",
                # Missing output_artifact_ref and output_schema_ref.
            }
        )
        adapter = _omp_adapter(fake)
        result = HarnessDispatcher().dispatch(request=_omp_request(), adapter=adapter)
        assert result.success is False
        assert result.dispatched is True
        assert result.error_code == "dispatch_exception"
        assert "missing" in (result.error_message or "").lower()


# ===========================================================================
# Worker 03: Cross-product adversarial boundaries
# ===========================================================================


class TestCrossProductThinkingRestrictions:
    def test_frozen_ocr_role_with_effort_fails_at_build(self) -> None:
        with pytest.raises(HarnessPolicyError, match="thinking-frozen|allowed_efforts"):
            build_request(
                node_contract=_node_contract(
                    role="product-ocr",
                    provider="paddle-official",
                    model="PaddleOCR-VL-1.6",
                    effort=ReasoningEffort.HIGH,
                    allowed_providers=("paddle-official",),
                ),
                skill=_skill(),
                role_entry=_ocr_role(),
                artifacts=(_artifact(),),
                selected_region="cn",
            )

    @pytest.mark.parametrize(
        "effort",
        [ReasoningEffort.LOW, ReasoningEffort.HIGH, ReasoningEffort.MAX],
    )
    def test_frozen_translation_role_rejects_non_none_efforts(
        self, effort: ReasoningEffort
    ) -> None:
        with pytest.raises(HarnessPolicyError, match="thinking-frozen|allowed_efforts"):
            build_request(
                node_contract=_node_contract(
                    role="product-translation",
                    harness="local-omlx",
                    provider="local-omlx",
                    model="dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX",
                    effort=effort,
                    allowed_providers=("local-omlx",),
                    allowed_regions=("local",),
                ),
                skill=_skill(),
                role_entry=_translation_role(),
                artifacts=(_artifact(),),
                selected_region="local",
            )

    def test_thinking_capable_role_accepts_max_effort(self) -> None:
        support_role_codex = _role_entry(
            role_id="product-ocr-translation-support",
            role_kind="ocr_translation_support",
            thinking=True,
            target=_target_profile(
                provider="codex-app",
                model="deepseek-v4-flash",
                harness="codex-app",
            ),
        )
        request = build_request(
            node_contract=_codex_node_contract(
                role="product-ocr-translation-support",
                effort=ReasoningEffort.MAX,
                provider="codex-app",
                allowed_providers=("codex-app",),
            ),
            skill=_skill(),
            role_entry=support_role_codex,
            artifacts=(_artifact(),),
            selected_region="cn",
        )
        assert request.reasoning_effort is ReasoningEffort.MAX


class TestCrossProductProviderRegionSensitivity:
    def test_selected_region_outside_allowlist_fails_closed(self) -> None:
        with pytest.raises(HarnessPolicyError, match="outside the node contract"):
            build_request(
                node_contract=_codex_node_contract(),
                skill=_skill(),
                role_entry=_codex_role(),
                artifacts=(_artifact(),),
                selected_region="unlisted",
            )

    def test_sensitivity_exceeds_ceiling_fails_closed(self) -> None:
        role = _role_entry(
            target=_target_profile(
                provider="codex-app",
                model="deepseek-v4-flash",
                harness="codex-app",
                sensitivity="internal",
            ),
        )
        with pytest.raises(HarnessPolicyError, match="ceiling"):
            build_request(
                node_contract=_codex_node_contract(
                    sensitivity=SensitivityTier.CONFIDENTIAL
                ),
                skill=_skill(),
                role_entry=role,
                artifacts=(_artifact(),),
                selected_region="cn",
            )


class TestCrossProductCredentialRejection:
    def test_credential_in_codex_snippet_fails_closed(self) -> None:
        with pytest.raises(HarnessPolicyError, match="credential-shaped"):
            build_request(
                node_contract=_codex_node_contract(),
                skill=_skill(),
                role_entry=_codex_role(),
                artifacts=(_artifact(snippet="token=sk-" + "a" * 30),),
                selected_region="cn",
            )

    def test_credential_in_payload_caught_by_dispatcher(self) -> None:
        # Uses DirectApiAdapter so the credential scan is reached after
        # preflight and probe without involving CLI schema resolution.
        secret_model = "sk-" + "a" * 30
        fake = _FakeDirectApi()
        adapter = DirectApiAdapter(
            provider="deepseek",
            model=secret_model,
            dispatch_fn=fake,
            probe_fn=fake.probe,
        )
        request = build_request(
            node_contract=_node_contract(model=secret_model),
            skill=_skill(),
            role_entry=_role_entry(target=_target_profile(model=secret_model)),
            artifacts=(_artifact(),),
            selected_region="cn",
        )
        result = HarnessDispatcher().dispatch(request=request, adapter=adapter)
        assert result.success is False
        assert result.error_code == "policy_credential_detected"
        assert fake.invocations == 0


class TestCrossProductNoRepositoryHandle:
    def test_codex_payload_has_no_repository_keys(self) -> None:
        payload = _codex_request().to_payload()
        forbidden = {"repository", "database", "db_handle", "connection"}
        assert not (set(payload.keys()) & forbidden)

    def test_omp_payload_has_no_repository_keys(self) -> None:
        payload = _omp_request().to_payload()
        forbidden = {"repository", "database", "db_handle", "connection"}
        assert not (set(payload.keys()) & forbidden)

    def test_payload_artifacts_are_logical_refs(self) -> None:
        payload = _codex_request().to_payload()
        for artifact in payload["input_artifacts"]:
            assert set(artifact.keys()) == {"ref", "sha256", "snippet"}
            assert "/" not in artifact["ref"] or _artifact_ref_valid(artifact["ref"])


def _artifact_ref_valid(ref: str) -> bool:
    """Check that ref is a valid logical artifact id (no path escape)."""
    import re

    return bool(re.fullmatch(r"[a-z][a-z0-9]*(?:[/_:-][a-z0-9]+)*", ref))


class TestCrossProductScratchpadExclusion:
    def test_fallback_excludes_scratchpad(self) -> None:
        fallback = FallbackInput(
            logical_call_id="lc:1",
            idempotency_key="idem-1",
            sensitivity_tier=SensitivityTier.CONFIDENTIAL,
            allowed_providers=("codex-app",),
            allowed_regions=("cn",),
            canonical_source={"content": "canonical text"},
            target_provider="codex-app",
            target_region="cn",
            previous_terminal_state="failed",
            previous_error_code="dispatch_exception",
            **_prior_fallback_evidence({"content": "canonical text"}),
            previous_provider_scratchpad={"internal": "secret-notes"},
            session_transcript=[{"turn": 1, "content": "prior-session"}],
            raw_sensitive_payload={"raw": "patient-data"},
        )
        payload = build_fallback_request(fallback)
        assert payload["content"] == "canonical text"
        assert "previous_provider_scratchpad" not in payload
        assert "internal" not in str(payload)
        assert "prior-session" not in str(payload)


class TestCrossProductSchemaMismatch:
    def test_receipt_schema_mismatch_fails_closed(self) -> None:
        # Uses DirectApiAdapter (worker_02-owned) so the full receipt
        # validation path is exercised, including schema equality.
        fake = _FakeDirectApi(
            receipt={
                "provider_session_id": "s",
                "output_sha256": OUTPUT_SHA,
                "observed_provider": "deepseek",
                "observed_model": "deepseek-v4-flash",
                "output_artifact_ref": "out",
                "output_schema_ref": "https://wrong/schema.json",
            }
        )
        adapter = DirectApiAdapter(
            provider="deepseek",
            model="deepseek-v4-flash",
            dispatch_fn=fake,
            probe_fn=fake.probe,
        )
        result = HarnessDispatcher().dispatch(
            request=_build_llm_request(), adapter=adapter
        )
        assert result.success is False
        assert result.error_code == "receipt_schema_mismatch"

    def test_codex_plan_binds_resolved_schema_path_not_uri(self) -> None:
        # The Codex command plan must carry the resolved local file path,
        # not the raw schema ref URI.
        adapter = _codex_adapter()
        request = _codex_request()
        plan = adapter.build_command_plan(request)
        idx = plan.index("--output-schema")
        resolved = plan[idx + 1]
        # The resolved path must be a real local file, not the URI.
        assert resolved != request.output_schema_ref
        assert os.path.isfile(resolved)
        assert "https://" not in resolved


class TestCrossProductProbeOnce:
    def test_codex_cached_probe_failure_never_dispatches(self) -> None:
        fake = _FakeCodexTransport()
        fake.probe_ok = False
        adapter = _codex_adapter(fake)
        dispatcher = HarnessDispatcher()
        r1 = dispatcher.dispatch(request=_codex_request(), adapter=adapter)
        r2 = dispatcher.dispatch(request=_codex_request(), adapter=adapter)
        assert r1.success is False
        assert r2.success is False
        assert r1.error_code == "probe_failed"
        assert r2.error_code == "probe_failed"
        assert fake.invocations == 0

    def test_omp_cached_probe_failure_never_dispatches(self) -> None:
        fake = _FakeOmpTransport()
        fake.probe_ok = False
        adapter = _omp_adapter(fake)
        dispatcher = HarnessDispatcher()
        r1 = dispatcher.dispatch(request=_omp_request(), adapter=adapter)
        r2 = dispatcher.dispatch(request=_omp_request(), adapter=adapter)
        assert r1.success is False
        assert r2.success is False
        assert r1.error_code == "probe_failed"
        assert r2.error_code == "probe_failed"
        assert fake.invocations == 0

    def test_codex_successful_probe_cached_no_reprobe(self) -> None:
        probe_count = 0

        def counting_probe() -> bool:
            nonlocal probe_count
            probe_count += 1
            return True

        fake = _FakeCodexTransport()
        adapter = CodexAppAdapter(
            provider="codex-app",
            model="deepseek-v4-flash",
            transport=fake,
            probe_fn=counting_probe,
            schema_path_resolver=_default_schema_resolver,
        )
        dispatcher = HarnessDispatcher()
        dispatcher.dispatch(request=_codex_request(), adapter=adapter)
        dispatcher.dispatch(request=_codex_request(), adapter=adapter)
        assert probe_count == 1


class TestCrossProductSameSessionRecovery:
    def test_codex_new_dispatch_has_no_resume(self) -> None:
        adapter = _codex_adapter()
        plan = adapter.build_command_plan(_codex_request())
        assert "resume" not in plan

    def test_codex_resumed_dispatch_uses_exec_resume(self) -> None:
        adapter = _codex_adapter()
        plan = adapter.build_command_plan(_codex_request(), session_id="sess-99")
        assert plan[1] == "exec"
        assert plan[2] == "resume"
        assert plan[3] == "sess-99"

    def test_omp_new_dispatch_has_no_resume(self) -> None:
        adapter = _omp_adapter()
        plan = adapter.build_command_plan(_omp_request())
        assert "--resume" not in plan

    def test_omp_resumed_dispatch_carries_session_id(self) -> None:
        adapter = _omp_adapter()
        plan = adapter.build_command_plan(_omp_request(), session_id="sess-7")
        idx = plan.index("--resume")
        assert plan[idx + 1] == "sess-7"

    def test_idempotency_key_never_used_as_session_id(self) -> None:
        adapter = _codex_adapter()
        request = _codex_request()
        plan = adapter.build_command_plan(request)
        assert "resume" not in plan
        assert request.idempotency_key not in plan

    def test_dispatcher_forwards_provider_session_id_codex(self) -> None:
        # The dispatcher forwards request.provider_session_id to the adapter.
        capture: list[tuple[list[str], dict[str, Any]]] = []
        fake = _FakeCodexTransport(capture=capture)
        adapter = _codex_adapter(fake)
        contract = _codex_node_contract(provider_session_id="codex-sess-recover")
        request = build_request(
            node_contract=contract,
            skill=_skill(),
            role_entry=_codex_role(),
            artifacts=(_artifact(),),
            selected_region="cn",
        )
        result = HarnessDispatcher().dispatch(request=request, adapter=adapter)
        assert result.success is True
        plan = capture[0][0]
        # Same-session recovery: exec resume with the provider_session_id.
        assert "resume" in plan
        assert "codex-sess-recover" in plan

    def test_dispatcher_forwards_provider_session_id_omp(self) -> None:
        capture: list[tuple[list[str], dict[str, Any]]] = []
        fake = _FakeOmpTransport(capture=capture)
        adapter = _omp_adapter(fake)
        contract = _omp_node_contract(provider_session_id="omp-sess-recover")
        request = build_request(
            node_contract=contract,
            skill=_skill(),
            role_entry=_omp_role(),
            artifacts=(_artifact(),),
            selected_region="cn",
        )
        result = HarnessDispatcher().dispatch(request=request, adapter=adapter)
        assert result.success is True
        plan = capture[0][0]
        assert "--resume" in plan
        idx = plan.index("--resume")
        assert plan[idx + 1] == "omp-sess-recover"


class TestCrossProductFallbackGating:
    def test_latency_does_not_trigger_fallback(self) -> None:
        with pytest.raises(HarnessFallbackError, match="eligible terminal"):
            build_fallback_request(
                FallbackInput(
                    logical_call_id="lc:1",
                    idempotency_key="idem-1",
                    sensitivity_tier=SensitivityTier.PUBLIC,
                    allowed_providers=("codex-app",),
                    allowed_regions=("cn",),
                    canonical_source={"content": "x"},
                    previous_terminal_state="",
                    previous_error_code="",
                )
            )

    def test_failed_terminal_state_makes_fallback_eligible(self) -> None:
        payload = build_fallback_request(
            FallbackInput(
                logical_call_id="lc:1",
                idempotency_key="idem-1",
                sensitivity_tier=SensitivityTier.PUBLIC,
                allowed_providers=("codex-app",),
                allowed_regions=("cn",),
                canonical_source={"content": "rebuild me"},
                target_provider="codex-app",
                target_region="cn",
                previous_terminal_state="failed",
                previous_error_code="dispatch_exception",
                **_prior_fallback_evidence({"content": "rebuild me"}),
            )
        )
        assert payload["content"] == "rebuild me"


class TestCrossProductProbeIdentity:
    def test_four_adapter_harnesses_have_distinct_identity_prefixes(self) -> None:
        direct = _direct_adapter()
        omlx = _omlx_adapter()
        codex = _codex_adapter()
        omp = _omp_adapter()
        identities = {direct.identity, omlx.identity, codex.identity, omp.identity}
        assert len(identities) == 4
        assert direct.identity.startswith("direct-api:")
        assert omlx.identity.startswith("local-omlx:")
        assert codex.identity.startswith("codex-app:")
        assert omp.identity.startswith("omp-cli:")

    def test_adapter_harness_mismatch_fails_before_probe_or_transport(self) -> None:
        fake = _FakeOmpTransport(
            receipt={
                "provider_session_id": "s",
                "output_sha256": OUTPUT_SHA,
                "observed_provider": "codex-app",
                "observed_model": "deepseek-v4-flash",
                "output_artifact_ref": "out",
                "output_schema_ref": OUTPUT_SCHEMA,
            }
        )
        adapter = OmpCliAdapter(
            provider="codex-app",
            model="deepseek-v4-flash",
            transport=fake,
            probe_fn=fake.probe,
        )
        result = HarnessDispatcher().dispatch(request=_codex_request(), adapter=adapter)
        assert result.error_code == "adapter_harness_mismatch"
        assert result.dispatched is False
        assert fake.probe_calls == 0
        assert fake.invocations == 0


class TestMandatoryProbeInjection:
    """Direct API and local oMLX constructors must reject missing probe_fn."""

    def test_direct_api_rejects_missing_probe_fn(self) -> None:
        with pytest.raises((ValueError, TypeError)):
            DirectApiAdapter(  # type: ignore[call-arg]
                provider="p",
                model="m",
                dispatch_fn=lambda p: {},
            )

    def test_local_omlx_rejects_missing_probe_fn(self) -> None:
        with pytest.raises((ValueError, TypeError)):
            LocalOmlxAdapter(  # type: ignore[call-arg]
                provider="p",
                model="m",
                dispatch_fn=lambda payload, lease: {},
            )


# ===========================================================================
# Worker 02 Recovery 02: four remaining P1 functional-contract bypasses
# ===========================================================================
#
# These tests are written FIRST (fail), then the smallest coherent repair is
# applied to make them pass.  They prove:
#
# 1. A missing/non-callable preflight must fail closed (no bypass).
# 2. Receipt fields must come from the physical transport; no fabricated defaults.
# 3. Observed identity mismatch (provider/model) is not success.
# 4. Direct construction of HarnessDispatchRequest cannot yield a dispatchable
#    request — only build_request() can.


class TestMissingPreflightMustFailClosed:
    """Gap 1: missing preflight must fail closed, not bypassed."""

    def test_adapter_without_preflight_returns_error(self) -> None:
        # An adapter missing preflight must not be treated as ready.
        fake = _FakeDirectApi()

        class _NoPreflightAdapter:
            identity = "direct-api:deepseek:deepseek-v4-flash"
            provider = "deepseek"
            model = "deepseek-v4-flash"
            harness = "direct-api"

            def probe(self) -> bool:
                return fake.probe()

            def dispatch(self, request: Any, **kwargs: Any) -> Any:
                return fake(request.to_payload())

        adapter = _NoPreflightAdapter()
        result = HarnessDispatcher().dispatch(
            request=_build_llm_request(), adapter=adapter
        )
        assert result.success is False
        assert result.dispatched is False
        assert result.error_code == "preflight_missing"
        assert fake.invocations == 0

    def test_adapter_with_non_callable_preflight_returns_error(self) -> None:
        fake = _FakeDirectApi()

        class _BadPreflightAdapter:
            identity = "direct-api:deepseek:deepseek-v4-flash"
            provider = "deepseek"
            model = "deepseek-v4-flash"
            harness = "direct-api"
            preflight = "not callable"

            def probe(self) -> bool:
                return fake.probe()

            def dispatch(self, request: Any, **kwargs: Any) -> Any:
                return fake(request.to_payload())

        result = HarnessDispatcher().dispatch(
            request=_build_llm_request(), adapter=_BadPreflightAdapter()
        )
        assert result.success is False
        assert result.dispatched is False
        assert result.error_code == "preflight_missing"

    def test_adapter_preflight_returning_non_outcome_returns_error(self) -> None:
        fake = _FakeDirectApi()

        class _BadOutcomeAdapter:
            identity = "direct-api:deepseek:deepseek-v4-flash"
            provider = "deepseek"
            model = "deepseek-v4-flash"
            harness = "direct-api"

            def preflight(self, request: Any) -> str:
                return "not an AdapterOutcome"

            def probe(self) -> bool:
                return fake.probe()

            def dispatch(self, request: Any, **kwargs: Any) -> Any:
                return fake(request.to_payload())

        result = HarnessDispatcher().dispatch(
            request=_build_llm_request(), adapter=_BadOutcomeAdapter()
        )
        assert result.success is False
        assert result.dispatched is False
        assert result.error_code == "preflight_invalid_result"


class TestNoFabricatedReceiptFields:
    """Gap 2: the physical transport must supply all receipt fields explicitly."""

    def test_direct_api_missing_observed_provider_fails(self) -> None:
        fake = _FakeDirectApi(
            receipt={
                "provider_session_id": "s",
                "output_sha256": OUTPUT_SHA,
                # observed_provider MISSING
                "observed_model": "deepseek-v4-flash",
                "output_artifact_ref": "out",
                "output_schema_ref": OUTPUT_SCHEMA,
            }
        )
        adapter = DirectApiAdapter(
            provider="deepseek",
            model="deepseek-v4-flash",
            dispatch_fn=fake,
            probe_fn=fake.probe,
        )
        result = HarnessDispatcher().dispatch(
            request=_build_llm_request(), adapter=adapter
        )
        assert result.success is False
        assert result.dispatched is True
        assert result.error_code == "dispatch_exception"

    def test_direct_api_missing_output_schema_ref_fails(self) -> None:
        fake = _FakeDirectApi(
            receipt={
                "provider_session_id": "s",
                "output_sha256": OUTPUT_SHA,
                "observed_provider": "deepseek",
                "observed_model": "deepseek-v4-flash",
                "output_artifact_ref": "out",
                # output_schema_ref MISSING
            }
        )
        adapter = DirectApiAdapter(
            provider="deepseek",
            model="deepseek-v4-flash",
            dispatch_fn=fake,
            probe_fn=fake.probe,
        )
        result = HarnessDispatcher().dispatch(
            request=_build_llm_request(), adapter=adapter
        )
        assert result.success is False
        assert result.dispatched is True

    def test_omlx_missing_observed_model_fails(self) -> None:
        fake = _FakeOmlxDispatch(
            receipt={
                "provider_session_id": "s",
                "output_sha256": OUTPUT_SHA,
                "observed_provider": "local-omlx",
                # observed_model MISSING
                "output_artifact_ref": "out",
                "output_schema_ref": OUTPUT_SCHEMA,
            }
        )
        adapter = LocalOmlxAdapter(
            provider="local-omlx",
            model="dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX",
            dispatch_fn=fake,
            probe_fn=fake.probe,
        )
        gate = _FakeOmlxGate(
            gate_selection={
                "models": {"translation": "dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX"}
            }
        )
        result = HarnessDispatcher().dispatch(
            request=_translation_request(),
            adapter=adapter,
            gate_selection=gate.gate_selection,
            lease_factory=gate.lease,
        )
        assert result.success is False
        assert result.dispatched is True


class TestObservedIdentityMismatchIsNotSuccess:
    """Gap 3: observed provider/model must match the validated request."""

    def test_direct_api_observed_provider_mismatch_fails(self) -> None:
        fake = _FakeDirectApi(
            receipt={
                "provider_session_id": "s",
                "output_sha256": OUTPUT_SHA,
                "observed_provider": "rogue-provider",  # mismatch
                "observed_model": "deepseek-v4-flash",
                "output_artifact_ref": "out",
                "output_schema_ref": OUTPUT_SCHEMA,
            }
        )
        adapter = DirectApiAdapter(
            provider="deepseek",
            model="deepseek-v4-flash",
            dispatch_fn=fake,
            probe_fn=fake.probe,
        )
        result = HarnessDispatcher().dispatch(
            request=_build_llm_request(), adapter=adapter
        )
        assert result.success is False
        assert result.dispatched is True
        assert result.error_code == "receipt_identity_mismatch"

    def test_direct_api_observed_model_mismatch_fails(self) -> None:
        fake = _FakeDirectApi(
            receipt={
                "provider_session_id": "s",
                "output_sha256": OUTPUT_SHA,
                "observed_provider": "deepseek",
                "observed_model": "rogue-model",  # mismatch
                "output_artifact_ref": "out",
                "output_schema_ref": OUTPUT_SCHEMA,
            }
        )
        adapter = DirectApiAdapter(
            provider="deepseek",
            model="deepseek-v4-flash",
            dispatch_fn=fake,
            probe_fn=fake.probe,
        )
        result = HarnessDispatcher().dispatch(
            request=_build_llm_request(), adapter=adapter
        )
        assert result.success is False
        assert result.dispatched is True
        assert result.error_code == "receipt_identity_mismatch"

    def test_gated_observed_model_mismatch_fails(self) -> None:
        fake = _FakeOmlxDispatch(
            receipt={
                "provider_session_id": "s",
                "output_sha256": OUTPUT_SHA,
                "observed_provider": "local-omlx",
                "observed_model": "rogue-model",  # mismatch
                "output_artifact_ref": "out",
                "output_schema_ref": OUTPUT_SCHEMA,
            }
        )
        adapter = LocalOmlxAdapter(
            provider="local-omlx",
            model="dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX",
            dispatch_fn=fake,
            probe_fn=fake.probe,
        )
        gate = _FakeOmlxGate(
            gate_selection={
                "models": {"translation": "dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX"}
            }
        )
        result = HarnessDispatcher().dispatch(
            request=_translation_request(),
            adapter=adapter,
            gate_selection=gate.gate_selection,
            lease_factory=gate.lease,
        )
        assert result.success is False
        assert result.dispatched is True
        assert result.error_code == "receipt_identity_mismatch"


class TestRequestMustProveBindingValidation:
    """Gap 4: direct construction of HarnessDispatchRequest must not be dispatchable."""

    def test_directly_constructed_request_is_rejected_by_dispatcher(self) -> None:
        # Forge a request bypassing build_request() — it lacks the validated
        # stamp.  The dispatcher must reject it before preflight/probe/transport.
        forged = HarnessDispatchRequest(
            node_execution_contract_id="nec:forged",
            skill_definition_id="skill.forged",
            role="product-llm",
            role_kind="llm",
            harness="direct-api",
            provider="deepseek",
            model="deepseek-v4-flash",
            reasoning_effort=ReasoningEffort.MAX,
            input_artifacts=(_artifact(),),
            input_schema_ref=INPUT_SCHEMA,
            output_schema_ref=OUTPUT_SCHEMA,
            allowed_tools=("deepseek-chat",),
            allowed_paths=("artifacts/chapter-draft/",),
            sensitivity_tier=SensitivityTier.CONFIDENTIAL,
            selected_region="cn",
            allowed_providers=("deepseek",),
            allowed_regions=("cn",),
            logical_call_id="lc:forged",
            idempotency_key="idem-forged",
            prompt_sha256=PROMPT_SHA,
            same_session_recovery=False,
        )
        fake = _FakeDirectApi()
        adapter = _direct_adapter(fake)
        result = HarnessDispatcher().dispatch(request=forged, adapter=adapter)
        assert result.success is False
        assert result.dispatched is False
        assert "unvalidated" in (result.error_code or "")
        assert fake.invocations == 0

    def test_validation_stamp_is_not_caller_constructible(self) -> None:
        from inspect import signature

        assert "_binding_evidence" not in signature(HarnessDispatchRequest).parameters

    def test_dispatcher_rechecks_session_recovery_polarity(self) -> None:
        request = _build_llm_request()
        object.__setattr__(request, "same_session_recovery", False)
        object.__setattr__(request, "provider_session_id", "forged-session")
        fake = _FakeDirectApi()
        result = HarnessDispatcher().dispatch(
            request=request, adapter=_direct_adapter(fake)
        )
        assert result.error_code == "session_recovery_not_authorized"
        assert result.dispatched is False
        assert fake.probe_calls == 0
        assert fake.invocations == 0

    def test_build_request_path_still_works(self) -> None:
        request = _build_llm_request()
        fake = _FakeDirectApi()
        adapter = _direct_adapter(fake)
        result = HarnessDispatcher().dispatch(request=request, adapter=adapter)
        assert result.success is True
        assert fake.invocations == 1


# ===========================================================================
# Worker 03 recovery 02: Codex/OMP preflight, mandatory probe, schema resolver
# ===========================================================================


class TestCliAdapterMandatoryProbe:
    """A missing or None probe_fn must fail at construction."""

    def test_codex_missing_probe_fn_rejected(self) -> None:
        with pytest.raises(ValueError, match="probe_fn must be injected"):
            CodexAppAdapter(
                provider="codex-app",
                model="deepseek-v4-flash",
                transport=_FakeCodexTransport(),
                probe_fn=None,  # type: ignore[arg-type]
                schema_path_resolver=_default_schema_resolver,
            )

    def test_omp_missing_probe_fn_rejected(self) -> None:
        with pytest.raises(ValueError, match="probe_fn must be injected"):
            OmpCliAdapter(
                provider="omp-cli",
                model="deepseek-v4-flash",
                transport=_FakeOmpTransport(),
                probe_fn=None,  # type: ignore[arg-type]
            )

    def test_codex_missing_schema_resolver_rejected(self) -> None:
        with pytest.raises(ValueError, match="schema_path_resolver must be injected"):
            CodexAppAdapter(
                provider="codex-app",
                model="deepseek-v4-flash",
                transport=_FakeCodexTransport(),
                probe_fn=lambda: True,
                schema_path_resolver=None,  # type: ignore[arg-type]
            )

    def test_codex_missing_transport_rejected(self) -> None:
        with pytest.raises(ValueError, match="transport must be injected"):
            CodexAppAdapter(
                provider="codex-app",
                model="deepseek-v4-flash",
                transport=None,  # type: ignore[arg-type]
                probe_fn=lambda: True,
                schema_path_resolver=_default_schema_resolver,
            )

    def test_omp_missing_transport_rejected(self) -> None:
        with pytest.raises(ValueError, match="transport must be injected"):
            OmpCliAdapter(
                provider="omp-cli",
                model="deepseek-v4-flash",
                transport=None,  # type: ignore[arg-type]
                probe_fn=lambda: True,
            )


class TestCliAdapterPreflight:
    """Preflight returns AdapterOutcome; mismatch fails before probe."""

    def test_codex_preflight_ok(self) -> None:
        adapter = _codex_adapter()
        outcome = adapter.preflight(_codex_request())
        assert isinstance(outcome, AdapterOutcome)
        assert outcome.ok is True

    def test_omp_preflight_ok(self) -> None:
        adapter = _omp_adapter()
        outcome = adapter.preflight(_omp_request())
        assert isinstance(outcome, AdapterOutcome)
        assert outcome.ok is True

    def test_codex_preflight_provider_mismatch(self) -> None:
        adapter = _codex_adapter()
        request = _codex_request()
        object.__setattr__(request, "provider", "wrong")
        outcome = adapter.preflight(request)
        assert outcome.ok is False
        assert outcome.error_code == "adapter_provider_mismatch"

    def test_omp_preflight_model_mismatch(self) -> None:
        adapter = _omp_adapter()
        request = _omp_request()
        object.__setattr__(request, "model", "wrong")
        outcome = adapter.preflight(request)
        assert outcome.ok is False
        assert outcome.error_code == "adapter_model_mismatch"


class TestCodexSchemaResolver:
    """Codex schema URI must resolve to a real local JSON file path."""

    def test_preflight_rejects_unmapped_schema_ref(self) -> None:
        fake = _FakeCodexTransport()
        adapter = CodexAppAdapter(
            provider="codex-app",
            model="deepseek-v4-flash",
            transport=fake,
            probe_fn=fake.probe,
            schema_path_resolver=lambda ref: None,
        )
        result = HarnessDispatcher().dispatch(request=_codex_request(), adapter=adapter)
        assert result.success is False
        assert result.dispatched is False
        assert result.error_code == "schema_ref_unmapped"
        assert fake.invocations == 0

    def test_preflight_rejects_nonexistent_file(self) -> None:
        fake = _FakeCodexTransport()
        adapter = CodexAppAdapter(
            provider="codex-app",
            model="deepseek-v4-flash",
            transport=fake,
            probe_fn=fake.probe,
            schema_path_resolver=lambda ref: "/nonexistent/schema.json",
        )
        result = HarnessDispatcher().dispatch(request=_codex_request(), adapter=adapter)
        assert result.success is False
        assert result.dispatched is False
        assert result.error_code == "schema_file_missing"
        assert fake.invocations == 0

    def test_preflight_rejects_non_json_file(self, tmp_path: Path) -> None:
        schema_path = tmp_path / "schema.txt"
        schema_path.write_text('{"type": "object"}', encoding="utf-8")
        fake = _FakeCodexTransport()
        adapter = CodexAppAdapter(
            provider="codex-app",
            model="deepseek-v4-flash",
            transport=fake,
            probe_fn=fake.probe,
            schema_path_resolver=lambda ref: str(schema_path),
        )
        result = HarnessDispatcher().dispatch(request=_codex_request(), adapter=adapter)
        assert result.success is False
        assert result.dispatched is False
        assert result.error_code == "schema_file_invalid"
        assert fake.invocations == 0

    def test_plan_uses_resolved_path_not_uri(self) -> None:
        adapter = _codex_adapter()
        request = _codex_request()
        plan = adapter.build_command_plan(request)
        idx = plan.index("--output-schema")
        path = plan[idx + 1]
        assert path != request.output_schema_ref
        assert os.path.isfile(path)

    def test_uri_never_emitted_in_plan(self) -> None:
        adapter = _codex_adapter()
        plan = adapter.build_command_plan(_codex_request())
        joined = " ".join(plan)
        assert "https://protocol-v3.local/" not in joined

    def test_resumed_plan_uses_resolved_path(self) -> None:
        adapter = _codex_adapter()
        plan = adapter.build_command_plan(_codex_request(), session_id="sess-recover")
        idx = plan.index("--output-schema")
        path = plan[idx + 1]
        assert os.path.isfile(path)
        assert "resume" in plan


class TestCliNoDuplicateDispatch:
    """No duplicate invocation on preflight/probe failures."""

    def test_codex_preflight_failure_no_duplicate(self) -> None:
        fake = _FakeCodexTransport()
        adapter = _codex_adapter(fake)
        request = _codex_request()
        object.__setattr__(request, "provider", "wrong")
        dispatcher = HarnessDispatcher()
        dispatcher.dispatch(request=request, adapter=adapter)
        dispatcher.dispatch(request=request, adapter=adapter)
        assert fake.invocations == 0

    def test_omp_probe_failure_no_duplicate(self) -> None:
        fake = _FakeOmpTransport()
        fake.probe_ok = False
        adapter = _omp_adapter(fake)
        dispatcher = HarnessDispatcher()
        dispatcher.dispatch(request=_omp_request(), adapter=adapter)
        dispatcher.dispatch(request=_omp_request(), adapter=adapter)
        assert fake.invocations == 0


class TestCliAdapterProtocolConformance:
    """Both adapters satisfy the TransportAdapter protocol shape."""

    def test_codex_has_all_protocol_members(self) -> None:
        adapter = _codex_adapter()
        assert hasattr(adapter, "identity")
        assert hasattr(adapter, "provider")
        assert hasattr(adapter, "model")
        assert callable(adapter.preflight)
        assert callable(adapter.probe)
        assert callable(adapter.dispatch)

    def test_omp_has_all_protocol_members(self) -> None:
        adapter = _omp_adapter()
        assert hasattr(adapter, "identity")
        assert hasattr(adapter, "provider")
        assert hasattr(adapter, "model")
        assert callable(adapter.preflight)
        assert callable(adapter.probe)
        assert callable(adapter.dispatch)

    def test_codex_dispatch_accepts_lease_kwarg(self) -> None:
        # The dispatch method must accept lease=None for protocol uniformity.
        fake = _FakeCodexTransport()
        adapter = _codex_adapter(fake)
        receipt = adapter.dispatch(_codex_request(), session_id=None, lease=None)
        assert receipt.observed_provider == "codex-app"

    def test_omp_dispatch_accepts_lease_kwarg(self) -> None:
        fake = _FakeOmpTransport()
        adapter = _omp_adapter(fake)
        receipt = adapter.dispatch(_omp_request(), session_id=None, lease=None)
        assert receipt.observed_provider == "omp-cli"
