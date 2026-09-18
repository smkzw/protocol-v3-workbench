"""Read-only binding to omp's stored zhipu-coding-plan API credentials.

No global AuthStorage constructor: it may migrate or deduplicate the source.
For a fresh no-session binding, omp selects login credentials in ascending row
order before static credentials. This resolver skips current persisted blocks,
selects once, and never retries a request or changes the provider. It does not
copy omp's quota/rotation platform. The returned string is memory-only transport
material and must never be included in a request artifact, receipt or log.
"""

from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import time
from typing import Mapping

PROVIDER = "zhipu-coding-plan"
PROVIDER_DEEPSEEK = "deepseek"


class OmpCredentialError(RuntimeError):
    """Stable code only; source content and database errors are not exposed."""


def _resolve_omp_api_key(provider: str, path: Path | None, now_ms: int | None,
                         environ: Mapping[str, str] | None) -> str:
    path = path if path is not None else Path.home() / ".omp/agent/agent.db"
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    environ = os.environ if environ is None else environ
    try:
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
            rows = db.execute(
                "SELECT id, data FROM auth_credentials "
                "WHERE provider=? AND credential_type='api_key' "
                "AND disabled_cause IS NULL ORDER BY id ASC", (provider,),
            ).fetchall()
            blocked = {
                row[0] for row in db.execute(
                    "SELECT credential_id FROM auth_credential_blocks "
                    "WHERE provider_key=? AND blocked_until_ms>?",
                    (provider + ":api_key", now_ms),
                )
            }
        decoded = [(row_id, json.loads(data)) for row_id, data in rows]
        if any(not isinstance(data, dict) for _, data in decoded):
            raise ValueError
    except (sqlite3.Error, ValueError, TypeError, OSError):
        raise OmpCredentialError("omp_credentials_unavailable") from None
    login = [(row_id, data) for row_id, data in decoded if data.get("source") == "login"]
    pool = login or decoded
    if not pool:
        raise OmpCredentialError("omp_credentials_unavailable")
    available = [data for row_id, data in pool if row_id not in blocked]
    if not available:
        raise OmpCredentialError("omp_credentials_temporarily_blocked")
    key = available[0].get("key")
    if not isinstance(key, str) or not key.strip():
        raise OmpCredentialError("omp_credentials_unavailable")
    if key.startswith("!"):
        raise OmpCredentialError("omp_credential_command_binding_unsupported")
    # omp's ordinary api_key form is an environment-name-or-literal binding.
    resolved = environ.get(key, key)
    if not resolved.strip():
        raise OmpCredentialError("omp_credentials_unavailable")
    return resolved


def resolve_omp_zhipu_key(
    path: Path | None = None, *, now_ms: int | None = None,
    environ: Mapping[str, str] | None = None,
) -> str:
    return _resolve_omp_api_key(PROVIDER, path, now_ms, environ)


def resolve_omp_deepseek_key(
    path: Path | None = None, *, now_ms: int | None = None,
    environ: Mapping[str, str] | None = None,
) -> str:
    """DeepSeek product credential: the same stored key omp's opencode-go
    provider binding uses.  Memory-only; identical read-only discipline."""
    return _resolve_omp_api_key(PROVIDER_DEEPSEEK, path, now_ms, environ)
