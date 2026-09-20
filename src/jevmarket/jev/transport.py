"""The wire shape of a Jev call, and the seam a real transport plugs into.

Jev (TypeSafe AI "System One") is not a chat model: it does not emit text. You
POST a `state` plus a dictionary of typed `questions` and it returns typed
`answers` -- a choice, a score, or a probability -- each with the model's own
probability distribution attached. That is why this project can hand it the
whole decision and still own every price.

    POST https://api.typesafe.ai/v1/systemone
    Authorization: Bearer $JEV_API_KEY

Nothing here performs I/O. `Transport` is the one method a live client must
implement; `MockTransport` implements it without a network so the entire
pipeline can be exercised for free.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Protocol

DEFAULT_BASE_URL = "https://api.typesafe.ai"
DEFAULT_ENDPOINT = "/v1/systemone"
DEFAULT_MODEL = "jev-latest"


def _canonical(value) -> str:
    """Stable JSON: sorted keys, no incidental whitespace, explicit unicode."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


@dataclass(frozen=True)
class JevRequest:
    """One System One call. Everything that can change an answer is in the key."""

    model: str
    state: dict[str, Any]
    questions: dict
    schema_version: str

    @property
    def cache_key(self) -> str:
        blob = _canonical(
            {
                "model": self.model,
                "state": self.state,
                "questions": self.questions,
                "schema_version": self.schema_version,
            }
        )
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def body(self) -> dict:
        """The JSON body to POST."""
        return {"model": self.model, "state": self.state, "questions": self.questions}

    def to_json(self) -> dict:
        return {
            "model": self.model,
            "state": self.state,
            "questions": self.questions,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_json(cls, data: dict) -> "JevRequest":
        return cls(
            model=data["model"],
            state=data["state"],
            questions=data["questions"],
            schema_version=data["schema_version"],
        )


@dataclass(frozen=True)
class JevResponse:
    """One System One answer set, plus what it cost to get it."""

    answers: dict
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_s: float = 0.0
    from_cache: bool = False

    def with_cache_flag(self, from_cache: bool) -> "JevResponse":
        return JevResponse(
            answers=self.answers,
            model=self.model,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            latency_s=self.latency_s,
            from_cache=from_cache,
        )

    def to_json(self) -> dict:
        return {
            "answers": self.answers,
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "latency_s": self.latency_s,
        }

    @classmethod
    def from_json(cls, data: dict) -> "JevResponse":
        return cls(
            answers=data["answers"],
            model=data["model"],
            input_tokens=data.get("input_tokens", 0),
            output_tokens=data.get("output_tokens", 0),
            latency_s=data.get("latency_s", 0.0),
        )


class Transport(Protocol):
    """The only thing a live Jev client has to implement."""

    def send(self, request: JevRequest) -> JevResponse: ...
