"""Thin diskcache wrapper with per-source TTL defaults.

Fetchers call ``cache.get(key)`` / ``cache.set(key, value, source=...)``; the
TTL for a source comes from :data:`DEFAULT_TTLS` unless the consumer overrides
it via the ``ttls`` constructor argument or an explicit ``ttl=`` argument to
:meth:`Cache.set`.

Consumers own the cache directory. The library never touches anything outside
the path the consumer passes in.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import diskcache


# Per ARCHITECTURE.md §7. Seconds.
DEFAULT_TTLS: dict[str, int] = {
    "reddit": 60 * 60,  # 1 hour
    "rss": 60 * 60,
    "article": 30 * 24 * 60 * 60,  # 30 days
    "youtube": 30 * 24 * 60 * 60,
    "bestbuy_api": 24 * 60 * 60,  # 1 day
    "dell": 7 * 24 * 60 * 60,
    "hp": 7 * 24 * 60 * 60,
    "lenovo": 7 * 24 * 60 * 60,
    "asus": 7 * 24 * 60 * 60,
    "bestbuy": 7 * 24 * 60 * 60,  # reviews
    "amazon": 7 * 24 * 60 * 60,
}


class Cache:
    """Consumer-scoped cache with per-source TTL defaults.

    ``directory`` is the consumer's cache path (created if missing).
    ``ttls`` overrides specific sources' default TTLs; anything not in
    ``ttls`` falls back to :data:`DEFAULT_TTLS`. Sources not in either
    have no default TTL — callers must pass ``ttl=`` explicitly.
    """

    def __init__(
        self,
        directory: str | Path,
        ttls: dict[str, int] | None = None,
    ) -> None:
        self._cache = diskcache.Cache(str(directory))
        self._ttls: dict[str, int] = {**DEFAULT_TTLS, **(ttls or {})}

    @staticmethod
    def make_key(source: str, url: str, **extra: Any) -> str:
        """Compose a deterministic cache key.

        Default shape: ``"{source}|{url}"`` optionally followed by
        ``|{k}={v}`` pairs sorted by key. Fetchers add ``extra`` when
        additional parameters meaningfully distinguish a fetch (pagination,
        search query, etc.).
        """
        parts = [source, url]
        for k in sorted(extra):
            parts.append(f"{k}={extra[k]}")
        return "|".join(parts)

    def get(self, key: str, default: Any = None) -> Any:
        return self._cache.get(key, default=default)

    def set(
        self,
        key: str,
        value: Any,
        *,
        source: str | None = None,
        ttl: int | None = None,
    ) -> None:
        """Store ``value`` under ``key``. TTL precedence: explicit ``ttl`` > source default > none."""
        effective_ttl: int | None
        if ttl is not None:
            effective_ttl = ttl
        elif source is not None:
            effective_ttl = self._ttls.get(source)
        else:
            effective_ttl = None
        self._cache.set(key, value, expire=effective_ttl)

    def delete(self, key: str) -> bool:
        """Remove ``key`` from the cache. Returns True if it was present."""
        return self._cache.delete(key)

    def clear(self) -> None:
        """Remove every entry from the cache."""
        self._cache.clear()

    def close(self) -> None:
        self._cache.close()

    def __enter__(self) -> Cache:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
