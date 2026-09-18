"""The live System One transport, exercised without touching the network.

`HttpTransport` takes an `opener` seam so every path -- auth, validation,
rate-limit backoff, overload, giving up -- is tested against a fake instead of
against TypeSafe's servers.
"""

import json

import pytest

from jevmarket.jev.http import (
    HttpTransport,
    JevAuthError,
    JevOverloaded,
    JevValidationError,
)
from jevmarket.jev.questions import build_request
from tests.test_jev_client import observation

OK_BODY = {
    "model": "jev-1.13.0",
    "answers": {
        "action": {
            "type": "choice",
            "choice": "buy",
            "probabilities": {"buy": 0.7, "sell": 0.2, "pass": 0.1},
            "confidence": 0.7,
        },
        "aggressiveness": {
            "type": "score",
            "score": 2.0,
            "legend": {"0": "none"},
            "probabilities": {"0": 1.0},
            "confidence": 0.5,
        },
        "already_priced": {"type": "noul", "noul": 0.3},
    },
    "usage": {"input_tokens": 314, "output_tokens": 27},
}


class FakeOpener:
    """Returns queued (status, body) pairs and records what it was sent."""

    def __init__(self, *responses):
        self.queue = list(responses)
        self.sent = []

    def __call__(self, url, body, headers, timeout):
        self.sent.append({"url": url, "body": body, "headers": headers})
        status, payload = self.queue.pop(0)
        return status, json.dumps(payload).encode("utf-8")


class RecordingSleep:
    def __init__(self):
        self.delays = []

    def __call__(self, seconds):
        self.delays.append(seconds)


def transport(opener, **kwargs):
    kwargs.setdefault("api_key", "apikey_test")
    kwargs.setdefault("sleep", RecordingSleep())
    return HttpTransport(opener=opener, **kwargs)


def test_posts_to_the_system_one_endpoint():
    opener = FakeOpener((200, OK_BODY))
    transport(opener).send(build_request(observation()))
    assert opener.sent[0]["url"] == "https://api.typesafe.ai/v1/systemone"


def test_authenticates_with_a_bearer_token():
    opener = FakeOpener((200, OK_BODY))
    transport(opener, api_key="apikey_secret").send(build_request(observation()))
    headers = opener.sent[0]["headers"]
    assert headers["Authorization"] == "Bearer apikey_secret"
    assert headers["Content-Type"] == "application/json"


def test_sends_state_model_and_questions_and_nothing_else():
    opener = FakeOpener((200, OK_BODY))
    transport(opener).send(build_request(observation()))
    body = json.loads(opener.sent[0]["body"])
    assert set(body) == {"state", "model", "questions"}
    assert body["model"] == "jev-latest"
    assert set(body["questions"]) == {"action", "aggressiveness", "already_priced"}


def test_parses_answers_and_usage():
    response = transport(FakeOpener((200, OK_BODY))).send(build_request(observation()))
    assert response.answers["action"]["choice"] == "buy"
    assert response.input_tokens == 314
    assert response.output_tokens == 27
    assert response.model == "jev-1.13.0"
    assert response.from_cache is False


def test_latency_is_recorded():
    response = transport(FakeOpener((200, OK_BODY))).send(build_request(observation()))
    assert response.latency_s >= 0.0


def test_a_missing_api_key_fails_at_construction_not_mid_sweep():
    with pytest.raises(ValueError):
        HttpTransport(api_key=None, env={}, opener=FakeOpener())


def test_the_key_is_read_from_the_environment_when_not_passed():
    opener = FakeOpener((200, OK_BODY))
    HttpTransport(
        opener=opener, env={"JEV_API_KEY": "apikey_from_env"}, sleep=RecordingSleep()
    ).send(build_request(observation()))
    assert opener.sent[0]["headers"]["Authorization"] == "Bearer apikey_from_env"


# --- documented error codes -------------------------------------------------


def test_401_raises_immediately_without_retrying():
    opener = FakeOpener((401, {"error": "bad key"}))
    with pytest.raises(JevAuthError):
        transport(opener).send(build_request(observation()))
    assert len(opener.sent) == 1


def test_422_raises_immediately_without_retrying():
    opener = FakeOpener((422, {"error": "bad questions"}))
    with pytest.raises(JevValidationError):
        transport(opener).send(build_request(observation()))
    assert len(opener.sent) == 1


def test_429_is_retried_and_can_succeed():
    opener = FakeOpener((429, {}), (429, {}), (200, OK_BODY))
    response = transport(opener).send(build_request(observation()))
    assert response.answers["action"]["choice"] == "buy"
    assert len(opener.sent) == 3


def test_529_overload_is_retried():
    opener = FakeOpener((529, {}), (200, OK_BODY))
    assert transport(opener).send(build_request(observation())).input_tokens == 314
    assert len(opener.sent) == 2


def test_backoff_is_exponential_not_immediate():
    sleep = RecordingSleep()
    opener = FakeOpener((429, {}), (429, {}), (429, {}), (200, OK_BODY))
    transport(opener, sleep=sleep, backoff_base=0.5).send(build_request(observation()))
    assert sleep.delays == [0.5, 1.0, 2.0]


def test_gives_up_after_the_retry_budget():
    opener = FakeOpener(*[(429, {})] * 4)
    with pytest.raises(JevOverloaded):
        transport(opener, max_retries=3).send(build_request(observation()))
    assert len(opener.sent) == 4


def test_an_unexpected_status_is_not_silently_swallowed():
    with pytest.raises(Exception):
        transport(FakeOpener((500, {}))).send(build_request(observation()))
