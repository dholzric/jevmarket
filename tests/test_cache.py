"""The response cache, keyed on Jev's actual request shape.

Phase 6 ships a public repo that reproduces every figure from this cache, so a
miss in read-only mode must be a loud error, never a silent live call.
"""

import json
import subprocess
import sys

import pytest

from jevmarket.jev.cache import CacheMiss, DecisionCache
from jevmarket.jev.transport import JevRequest, JevResponse

QUESTIONS = {
    "action": {
        "type": "choice",
        "instructions": "Buy, sell, or pass.",
        "criteria": {"buy": "underpriced", "sell": "overpriced", "pass": "unclear"},
    }
}


def request(state="best bid 99, best ask 101, your value 104", **kwargs):
    base = dict(
        model="jev-latest",
        state=state,
        questions=QUESTIONS,
        schema_version="v1",
    )
    base.update(kwargs)
    return JevRequest(**base)


def response(choice="buy"):
    return JevResponse(
        answers={
            "action": {
                "choice": choice,
                "probabilities": {"buy": 0.7, "sell": 0.2, "pass": 0.1},
                "confidence": 0.7,
            }
        },
        model="jev-1.13.0",
        input_tokens=100,
        output_tokens=20,
        latency_s=0.4,
    )


def test_a_miss_returns_none(tmp_path):
    cache = DecisionCache(tmp_path)
    assert cache.get(request()) is None
    assert cache.misses == 1
    assert cache.hits == 0


def test_a_stored_response_is_returned_on_the_next_get(tmp_path):
    cache = DecisionCache(tmp_path)
    cache.put(request(), response())
    hit = cache.get(request())
    assert hit is not None
    assert hit.answers["action"]["choice"] == "buy"
    assert cache.hits == 1


def test_a_cached_response_is_marked_as_coming_from_cache(tmp_path):
    cache = DecisionCache(tmp_path)
    cache.put(request(), response())
    assert response().from_cache is False
    assert cache.get(request()).from_cache is True


def test_the_cache_survives_being_reopened(tmp_path):
    DecisionCache(tmp_path).put(request(), response())
    assert DecisionCache(tmp_path).get(request()) is not None


def test_any_change_to_the_request_is_a_different_key(tmp_path):
    cache = DecisionCache(tmp_path)
    cache.put(request(), response())
    other_questions = {
        "action": {
            "type": "choice",
            "instructions": "DIFFERENT WORDING.",
            "criteria": {"buy": "underpriced", "sell": "overpriced", "pass": "unclear"},
        }
    }
    for changed in (
        request(state="best bid 98, best ask 101, your value 104"),
        request(model="jev-1.13.0"),
        request(questions=other_questions),
        request(schema_version="v2"),
    ):
        assert cache.get(changed) is None, f"key collided on {changed.cache_key}"


def test_key_does_not_depend_on_dict_ordering(tmp_path):
    """Same request, keys written in a different order, must be one cache entry."""
    reordered = {
        "action": {
            "criteria": {"sell": "overpriced", "pass": "unclear", "buy": "underpriced"},
            "instructions": "Buy, sell, or pass.",
            "type": "choice",
        }
    }
    assert request().cache_key == request(questions=reordered).cache_key


def test_the_key_is_stable_across_processes(tmp_path):
    """Not Python's salted string hash: a key must mean the same thing forever."""
    script = (
        "import sys; sys.path.insert(0, 'src');"
        "from jevmarket.jev.transport import JevRequest;"
        f"print(JevRequest(model='jev-latest', state={request().state!r},"
        f" questions={QUESTIONS!r}, schema_version='v1').cache_key)"
    )
    out = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True
    )
    assert out.stdout.strip() == request().cache_key
    assert len(request().cache_key) == 64


def test_read_only_cache_raises_on_a_miss(tmp_path):
    cache = DecisionCache(tmp_path, read_only=True)
    with pytest.raises(CacheMiss):
        cache.get(request())


def test_read_only_cache_still_serves_hits(tmp_path):
    DecisionCache(tmp_path).put(request(), response())
    assert DecisionCache(tmp_path, read_only=True).get(request()) is not None


def test_read_only_cache_refuses_to_write(tmp_path):
    cache = DecisionCache(tmp_path, read_only=True)
    with pytest.raises(CacheMiss):
        cache.put(request(), response())


def test_entries_are_human_readable_json_on_disk(tmp_path):
    """The cache is committed to the public repo, so it has to be reviewable."""
    cache = DecisionCache(tmp_path)
    cache.put(request(), response())
    files = list(tmp_path.rglob("*.json"))
    assert len(files) == 1
    stored = json.loads(files[0].read_text(encoding="utf-8"))
    assert stored["request"]["state"] == request().state
    assert stored["response"]["answers"]["action"]["choice"] == "buy"


def test_hit_rate_is_reported(tmp_path):
    cache = DecisionCache(tmp_path)
    cache.get(request())
    cache.put(request(), response())
    cache.get(request())
    assert cache.hit_rate == pytest.approx(0.5)
