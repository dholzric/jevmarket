"""Ordered archive of live calls, and a transport that replays it.

The content-addressed cache memoises: one stored response per distinct state,
shared by every trader that renders it. Prereg 10h needs the opposite -- a
fresh call per decision -- while keeping the run reproducible from disk. So a
run under independent calling appends every response, in call order, to a
`CallLog`, and a later run can be driven from that log by `ReplayTransport`,
which serves the archived responses back in the same order and refuses any
request whose key differs from the one archived at that position.

The cache directory is never involved. Writing fresh responses into it would
overwrite the entries the memoised confirmatory runs replay from.
"""

from __future__ import annotations

import gzip
import json
import pathlib

from .transport import JevRequest, JevResponse


class ReplayMismatch(Exception):
    """The run asked for something other than what was archived at this point."""


class ReplayExhausted(Exception):
    """The run asked for more calls than the archive holds."""


class CallLog:
    def __init__(self, entries: list[dict] | None = None) -> None:
        self.entries: list[dict] = list(entries or [])

    def record(self, request: JevRequest, response: JevResponse) -> None:
        self.entries.append(
            {
                "cache_key": request.cache_key,
                "request": request.to_json(),
                "response": response.to_json(),
            }
        )

    def save(self, path) -> None:
        path = pathlib.Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(path, "wt", encoding="utf-8") as fh:
            json.dump(self.entries, fh, sort_keys=True, ensure_ascii=True)

    @classmethod
    def load(cls, path) -> "CallLog":
        with gzip.open(pathlib.Path(path), "rt", encoding="utf-8") as fh:
            return cls(json.load(fh))

    def __len__(self) -> int:
        return len(self.entries)


class ReplayTransport:
    """Serve an archived run back in order. No I/O, no cost."""

    def __init__(self, log: CallLog) -> None:
        self.log = log
        self.position = 0

    def send(self, request: JevRequest) -> JevResponse:
        if self.position >= len(self.log.entries):
            raise ReplayExhausted(
                f"archive holds {len(self.log.entries)} calls; the run asked for more"
            )
        entry = self.log.entries[self.position]
        if entry["cache_key"] != request.cache_key:
            raise ReplayMismatch(
                f"call {self.position}: archive has {entry['cache_key'][:12]}, "
                f"run asked for {request.cache_key[:12]}"
            )
        self.position += 1
        return JevResponse.from_json(entry["response"])
