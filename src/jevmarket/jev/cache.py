"""Content-addressed cache of Jev responses.

Every live answer is written to disk as reviewable JSON keyed by the sha256 of
the canonical request. Two consequences the plan depends on:

- reruns during Phases 4-5 cost nothing, so seeds are cheap to add;
- Phase 6 can publish the cache and let a reader reproduce every figure with
  `read_only=True`, where a miss raises instead of quietly calling the API.
"""

from __future__ import annotations

import json
import pathlib

from .transport import JevRequest, JevResponse


class CacheMiss(Exception):
    """A read-only cache was asked for something it does not have."""


class DecisionCache:
    def __init__(self, path, read_only: bool = False) -> None:
        self.path = pathlib.Path(path)
        self.read_only = read_only
        self.hits = 0
        self.misses = 0
        if not read_only:
            self.path.mkdir(parents=True, exist_ok=True)

    # Shard by the first two hex characters: 256 directories instead of one
    # with a hundred thousand files in it.
    def _entry_path(self, key: str) -> pathlib.Path:
        return self.path / key[:2] / f"{key}.json"

    def get(self, request: JevRequest) -> JevResponse | None:
        entry = self._entry_path(request.cache_key)
        if entry.is_file():
            self.hits += 1
            stored = json.loads(entry.read_text(encoding="utf-8"))
            return JevResponse.from_json(stored["response"]).with_cache_flag(True)

        self.misses += 1
        if self.read_only:
            raise CacheMiss(
                f"no cached response for {request.cache_key} and the cache is "
                f"read-only; rerun with a live transport to populate it"
            )
        return None

    def put(self, request: JevRequest, response: JevResponse) -> None:
        if self.read_only:
            raise CacheMiss("cache is read-only; refusing to write")
        entry = self._entry_path(request.cache_key)
        entry.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "cache_key": request.cache_key,
            "request": request.to_json(),
            "response": response.to_json(),
        }
        entry.write_text(
            json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True),
            encoding="utf-8",
        )

    @property
    def lookups(self) -> int:
        return self.hits + self.misses

    @property
    def hit_rate(self) -> float:
        return self.hits / self.lookups if self.lookups else float("nan")
