"""DeepSeek direct-API product transport on the shared chat-completions stack.

默认行为不变：直连 api.deepseek.com，凭证取自 omp 的 agent 库
（provider='deepseek'）。T17 第九轮起支持部署级覆盖，把同一适配器指向
cms-router/OmniRoute 本机网关（key 轮转池，响应 model 字段会被网关重写）：

- ``WORKBENCH_PROTOCOL_V3_AI_ENDPOINT``：完整 chat/completions URL；
- ``WORKBENCH_PROTOCOL_V3_AI_MODEL``：请求模型名（如 deepseek-flash）；
- ``WORKBENCH_PROTOCOL_V3_AI_KEY``：Bearer 凭证（优先于 omp 库解析）；
- ``WORKBENCH_PROTOCOL_V3_AI_EXPECTED_MODEL``：响应 model 的出口声明
  （网关池重写 model 字段时用于校验；缺省维持严格相等）；
- ``WORKBENCH_PROTOCOL_V3_AI_MAX_TOKENS``：完成请求的 max_tokens 输出
  预算（推理模型在网关默认输出上限下会被 finish_reason=length 截断；
  缺省不发该字段）。

未设置任何覆盖变量时，本模块与历史行为完全一致。
"""
import os

from app.protocol_workflow.runtime.omp_credentials import resolve_omp_deepseek_key
from .zhipu_api import build_zhipu_api_adapter

DEEPSEEK_CHAT_COMPLETIONS_ENDPOINT = "https://api.deepseek.com/chat/completions"
DEEPSEEK_PROVIDER_ID = "deepseek"
DEEPSEEK_DEFAULT_MODEL = "deepseek-flash"  # observed id from the live API (2026-09-19 probe)

__all__ = [
    "DEEPSEEK_CHAT_COMPLETIONS_ENDPOINT",
    "DEEPSEEK_DEFAULT_MODEL",
    "build_deepseek_api_adapter",
]


def build_deepseek_api_adapter(
    *,
    model: str = DEEPSEEK_DEFAULT_MODEL,
    credential_resolver=None,
    endpoint: str = DEEPSEEK_CHAT_COMPLETIONS_ENDPOINT,
    expected_response_model_override: str | None = None,
    **kwargs,
):
    """Compose the DeepSeek direct-API adapter over the shared transport.

    All other builder discipline (receipt sinks, full artifact input budget,
    injected openers for tests) is inherited unchanged.  The transport error
    strings carry the deepseek label; receipts carry the API-observed identity.
    """
    # 部署级覆盖必须三者同源生效：端点、凭证、出口模型声明。此前
    # KEY/EXPECTED_MODEL 已实现而 ENDPOINT/MODEL 缺失，导致网关凭证被
    # 发往直连端点（401→probe_failed→unknown_outcome 且不可诊断）。
    endpoint_override = os.environ.get(
        "WORKBENCH_PROTOCOL_V3_AI_ENDPOINT", "").strip()
    if endpoint_override:
        endpoint = endpoint_override
    model_override = os.environ.get(
        "WORKBENCH_PROTOCOL_V3_AI_MODEL", "").strip()
    if model_override:
        model = model_override
    key_override = os.environ.get("WORKBENCH_PROTOCOL_V3_AI_KEY", "").strip()
    if key_override:
        credential_resolver = lambda: key_override  # noqa: E731 — 部署级覆盖
    expected_model = os.environ.get(
        "WORKBENCH_PROTOCOL_V3_AI_EXPECTED_MODEL", "").strip()
    if expected_model:
        expected_response_model_override = expected_model
    max_tokens_override = os.environ.get(
        "WORKBENCH_PROTOCOL_V3_AI_MAX_TOKENS", "").strip()
    if max_tokens_override.isdigit():
        kwargs["max_output_tokens"] = int(max_tokens_override)

    return build_zhipu_api_adapter(
        model=model,
        provider_id=DEEPSEEK_PROVIDER_ID,
        provider_label="deepseek",
        credential_resolver=credential_resolver,
        endpoint=endpoint,
        expected_response_model_override=expected_response_model_override,
        **kwargs,
    )
