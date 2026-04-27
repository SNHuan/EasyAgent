from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from typing import Any


@dataclass
class _Revision:
    version: int
    value: Any
    producer: str | None = None


class SharedStore:
    """Versioned key/value shared across agents.

    Purely additive: writing a new value for a key creates a new revision;
    history is never erased. Agents typically access the store via a tool,
    never directly — but the SDK exposes it for users who want to build
    coordination primitives (artifacts, blackboards, shared docs).

    Thread-safe for mixed async/sync access.
    """

    def __init__(self) -> None:
        self._revisions: dict[str, list[_Revision]] = {}
        self._lock = Lock()

    def put(self, key: str, value: Any, *, producer: str | None = None) -> int:
        with self._lock:
            revs = self._revisions.setdefault(key, [])
            version = len(revs) + 1
            revs.append(_Revision(version=version, value=value, producer=producer))
            return version

    def get(self, key: str, *, version: int | None = None) -> Any:
        with self._lock:
            revs = self._revisions.get(key)
            if not revs:
                raise KeyError(key)
            if version is None:
                return revs[-1].value
            for rev in revs:
                if rev.version == version:
                    return rev.value
            raise KeyError(f"{key}@{version}")

    def has(self, key: str) -> bool:
        with self._lock:
            return key in self._revisions

    def history(self, key: str) -> list[tuple[int, Any, str | None]]:
        with self._lock:
            revs = self._revisions.get(key, [])
            return [(r.version, r.value, r.producer) for r in revs]

    def keys(self) -> list[str]:
        with self._lock:
            return list(self._revisions.keys())

    def snapshot(self) -> dict[str, Any]:
        """Latest value for every key — convenient for prompts/debugging."""
        with self._lock:
            return {k: revs[-1].value for k, revs in self._revisions.items() if revs}
