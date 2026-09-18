"""Complete bound text for product messages; no repository or filesystem access."""
from collections.abc import Callable, Sequence
import hashlib


def resolve_artifact_messages(
    artifacts: Sequence[dict], resolver: Callable[[str, str], str], *, max_input_bytes: int,
) -> list[dict[str, str]]:
    """Read through an application-supplied resolver and account for the whole body.

    ``max_input_bytes`` is a conservative byte budget chosen from the declared
    model profile with output/template headroom. It is not a tokenizer count.
    Material is complete or rejected; no partial document is sent as complete.
    """
    if isinstance(max_input_bytes, bool) or not isinstance(max_input_bytes, int) or max_input_bytes <= 0:
        raise ValueError('full artifact input budget must be a positive byte count')
    if not artifacts:
        raise ValueError('full artifact input requires material')
    parts = []
    size = 0
    for artifact in artifacts:
        if not isinstance(artifact, dict) or not all(
            isinstance(artifact.get(key), str) and artifact[key].strip() for key in ('ref', 'sha256')
        ):
            raise ValueError('full artifact input reference is malformed')
        text = resolver(artifact['ref'], artifact['sha256'])
        if not isinstance(text, str) or not text.strip():
            raise ValueError('full artifact input text is unavailable')
        if hashlib.sha256(text.encode('utf-8')).hexdigest() != artifact['sha256']:
            raise ValueError('artifact content hash does not match the selected version')
        part = f"[{artifact['ref']} | sha256:{artifact['sha256']}]\n{text}"
        size += len(part.encode('utf-8')) + (2 if parts else 0)
        if size > max_input_bytes:
            raise ValueError('full artifact input budget exceeded; no material was truncated')
        parts.append(part)
    return [{'role': 'user', 'content': '\n\n'.join(parts)}]
