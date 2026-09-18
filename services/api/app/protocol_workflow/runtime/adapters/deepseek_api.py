"""DeepSeek direct-API product transport on the shared chat-completions stack.

The DeepSeek official API is OpenAI-compatible chat completions with Bearer
auth; the credential is the same stored key omp's opencode-go binding uses
(``auth_credentials.provider='deepseek'``), resolved read-only and kept in
memory only.  The product default profile per the 2026-09-13 goal: model
``deepseek-v4-flash`` (registry ``role_registry.deepseek.json``),
reasoning effort ``max`` — declared identities only; the observed model must
match at the transport boundary or the completion fails typed.
"""
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
    credential_resolver=resolve_omp_deepseek_key,
    **kwargs,
):
    """Compose the DeepSeek direct-API adapter over the shared transport.

    All other builder discipline (receipt sinks, full artifact input budget,
    injected openers for tests) is inherited unchanged.  The transport error
    strings carry the deepseek label; receipts carry the API-observed identity.
    """
    return build_zhipu_api_adapter(
        model=model,
        provider_id=DEEPSEEK_PROVIDER_ID,
        provider_label="deepseek",
        credential_resolver=credential_resolver,
        endpoint=DEEPSEEK_CHAT_COMPLETIONS_ENDPOINT,
        **kwargs,
    )
