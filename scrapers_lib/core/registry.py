"""Internal fetcher registry keyed by source-name string.

Every fetcher module (``tier1/reddit.py``, ``tier2/dell.py``, etc.) registers
its public fetcher callable under a short source-name (``"reddit"``,
``"dell"``). The Scheduler looks up fetchers by name when draining jobs.

All fetchers follow the same signature::

    Callable[[str, list[Anchor] | None, **fetch_options],
             list[RawMention] | list[ProductSnapshot]]

This shared signature is what makes a future plugin-registration API
(exposing :func:`register_fetcher` to third parties) a non-breaking addition.
"""

from __future__ import annotations

from typing import Callable, TypeAlias


FetcherFn: TypeAlias = Callable[..., list]

_registry: dict[str, FetcherFn] = {}


def register_fetcher(name: str, fn: FetcherFn, *, replace: bool = False) -> None:
    """Register ``fn`` under ``name``.

    Raises :class:`ValueError` if a fetcher is already registered under
    ``name`` unless ``replace=True``.
    """
    if not name:
        raise ValueError("fetcher name must be non-empty")
    if name in _registry and not replace:
        raise ValueError(f"fetcher {name!r} already registered")
    _registry[name] = fn


def register(name: str, *, replace: bool = False) -> Callable[[FetcherFn], FetcherFn]:
    """Decorator form of :func:`register_fetcher`.

    Usage::

        @register("rss")
        def fetch_feed(url, anchors=None, **opts):
            ...
    """

    def _decorator(fn: FetcherFn) -> FetcherFn:
        register_fetcher(name, fn, replace=replace)
        return fn

    return _decorator


def get_fetcher(name: str) -> FetcherFn:
    """Return the fetcher registered under ``name``.

    Raises :class:`KeyError` if nothing is registered.
    """
    if name not in _registry:
        raise KeyError(f"no fetcher registered for {name!r}")
    return _registry[name]


def list_fetchers() -> list[str]:
    """Return registered source-names in sorted order."""
    return sorted(_registry.keys())


def _reset_for_tests() -> None:
    """Test-only: clear the registry."""
    _registry.clear()
