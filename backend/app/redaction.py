"""M10: response-layer secret redaction.

Credentials must remain available to execution, so persistence is NOT
altered: test_runs.json / executions.json still hold the real values (they
are protected by file permissions, see docs/architecture.md). Instead,
everything that leaves the API — test-run responses, execution responses,
and the data feeding generated reports — passes through here first.

Two layers:
* Key-based: any dict entry whose key looks sensitive (`env_user`,
  `*secret*`, `*password*`, `*token*`, `*credential*`, `*private*`,
  `*api_key*`, `authorization`, `cookie`, `jwk(s)`, ...) has its value
  replaced. Applied recursively, so it also covers arbitrary
  OpenID `plan_configuration` content and future fields.
* Text-based (execution evidence only): secret-shaped substrings in free
  text (process output, failure summaries, messages) are scrubbed with the
  same patterns the subprocess layer already uses, plus PEM private keys.
"""

import re
from typing import Any, TypeVar

from pydantic import BaseModel

from app.inji_process import sanitize_output

REDACTED = "[REDACTED]"

_SENSITIVE_KEY = re.compile(
    r"(?i)(secret|passw(or)?d|token|credential|private|api[_-]?key|access[_-]?key"
    r"|authorization|cookie|bearer|jwks?|env_user|assertion)"
)
_PEM_PRIVATE_KEY = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?(-----END [A-Z0-9 ]*PRIVATE KEY-----|\Z)",
    re.DOTALL,
)

# Execution subtrees carrying provider/process-originated free text.
_EVIDENCE_KEYS = frozenset({"step_results", "normalized_results"})

M = TypeVar("M", bound=BaseModel)


def redact_text(text: str) -> str:
    return _PEM_PRIVATE_KEY.sub(REDACTED, sanitize_output(text))


def _redact(value: Any, scrub_text: bool) -> Any:
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if isinstance(key, str) and _SENSITIVE_KEY.search(key):
                out[key] = None if item is None else REDACTED
            else:
                out[key] = _redact(
                    item, scrub_text or (isinstance(key, str) and key in _EVIDENCE_KEYS)
                )
        return out
    if isinstance(value, list):
        return [_redact(item, scrub_text) for item in value]
    if isinstance(value, str):
        if scrub_text:
            return redact_text(value)
        return _PEM_PRIVATE_KEY.sub(REDACTED, value)
    return value


def redact_model(model: M) -> M:
    """A redacted copy of a TestRunConfig/Execution; the original (which
    execution still needs) is untouched."""
    data = _redact(model.model_dump(mode="json"), scrub_text=False)
    return type(model).model_validate(data)

