"""Live TypeSafe System One transport.

    POST https://api.typesafe.ai/v1/systemone
    Authorization: Bearer $JEV_API_KEY

Status handling, and what each means for a sweep:

    401       missing or invalid key     -> fatal, stop now
    422       request failed validation  -> fatal, the frozen questions are wrong
    429       rate limited               -> retry with exponential backoff
    5xx       server or proxy failure    -> retry with exponential backoff
    other 4xx                            -> fatal, surfaced rather than swallowed

TypeSafe documents only 401/422/429/529. The 5xx rule is wider than their list
because a live sweep died on an undocumented 503 from their edge proxy. Any 5xx
is transient by definition; any 4xx is the server rejecting the request on its
merits, where retrying only burns money.

Retryable failures back off exponentially, per TypeSafe's own guidance. The
`opener` and `sleep` arguments are injection seams so every path above is
tested against a fake rather than against their servers.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

from .transport import DEFAULT_BASE_URL, DEFAULT_ENDPOINT, JevRequest, JevResponse

# TypeSafe documents 401 / 422 / 429 / 529. In practice their edge also emits
# bare 5xx: a live sweep died on
#   503 "upstream connect error or disconnect/reset before headers ...
#        delayed connect error: Connection refused"
# which is a transient proxy failure, not a rejection of the request. Anything
# 5xx is therefore retried; 4xx never is, because the server has rejected the
# request on its merits and retrying only burns money.
RETRYABLE_STATUSES = {429}
DEFAULT_MAX_RETRIES = 8
DEFAULT_BACKOFF_BASE = 0.5
DEFAULT_TIMEOUT_S = 30.0


class JevHttpError(Exception):
    """Any non-200 from System One."""


class JevAuthError(JevHttpError):
    """401. The key is missing or invalid. Never retried."""


class JevValidationError(JevHttpError):
    """422. The request body was rejected. Never retried -- the questions are wrong."""


class JevOverloaded(JevHttpError):
    """429 or 529 that survived the retry budget."""


def _urlopen(url: str, body: bytes, headers: dict, timeout: float):
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


class HttpTransport:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = DEFAULT_BASE_URL,
        endpoint: str = DEFAULT_ENDPOINT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        backoff_base: float = DEFAULT_BACKOFF_BASE,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        opener=_urlopen,
        sleep=time.sleep,
        env: dict | None = None,
    ) -> None:
        env = os.environ if env is None else env
        self.api_key = api_key or env.get("JEV_API_KEY")
        if not self.api_key:
            raise ValueError(
                "no Jev API key: pass api_key= or set JEV_API_KEY. Failing here "
                "rather than partway through a paid sweep."
            )
        self.url = base_url.rstrip("/") + endpoint
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.timeout_s = timeout_s
        self.opener = opener
        self.sleep = sleep

    def send(self, request: JevRequest) -> JevResponse:
        body = json.dumps(request.body()).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        started = time.monotonic()
        for attempt in range(self.max_retries + 1):
            try:
                status, raw = self.opener(self.url, body, headers, self.timeout_s)
            except (urllib.error.URLError, OSError) as error:
                # Socket-level failure: connection reset, refused, or timed out
                # before any status arrived. Seen live as WinError 10054 during
                # the 10h sweep. As transient as a 503, and retried the same way.
                if attempt == self.max_retries:
                    raise JevOverloaded(
                        f"connection failure against {self.url} after "
                        f"{attempt + 1} attempts: {error}"
                    ) from error
                self.sleep(self.backoff_base * (2**attempt))
                continue

            if status == 200:
                return self._parse(raw, time.monotonic() - started)
            if status == 401:
                raise JevAuthError(f"401 from {self.url}: {raw[:200]!r}")
            if status == 422:
                raise JevValidationError(
                    f"422 from {self.url}; the frozen questions were rejected: "
                    f"{raw[:400]!r}"
                )
            if status in RETRYABLE_STATUSES or 500 <= status < 600:
                if attempt == self.max_retries:
                    raise JevOverloaded(
                        f"{status} from {self.url} after {attempt + 1} attempts"
                    )
                self.sleep(self.backoff_base * (2**attempt))
                continue

            raise JevHttpError(f"unexpected {status} from {self.url}: {raw[:200]!r}")

        raise JevOverloaded(f"exhausted retries against {self.url}")

    @staticmethod
    def _parse(raw: bytes, latency_s: float) -> JevResponse:
        payload = json.loads(raw.decode("utf-8"))
        usage = payload.get("usage") or {}
        return JevResponse(
            answers=payload["answers"],
            model=payload.get("model", "unknown"),
            input_tokens=int(usage.get("input_tokens", 0)),
            output_tokens=int(usage.get("output_tokens", 0)),
            latency_s=latency_s,
        )
