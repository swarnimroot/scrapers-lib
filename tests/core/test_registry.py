"""Unit tests for scrapers_lib.core.registry."""

import pytest

from scrapers_lib.core import registry as _registry_mod
from scrapers_lib.core.registry import (
    FetcherFn,
    get_fetcher,
    list_fetchers,
    register,
    register_fetcher,
)


@pytest.fixture(autouse=True)
def _isolate_registry():
    """Snapshot-and-restore the registry around each test.

    Tests in this file need a clean slate to verify register/get semantics,
    but other test modules (and production code) may have registered real
    fetchers at import time. Snapshotting preserves those while isolating
    this file's mutations.
    """
    snapshot = dict(_registry_mod._registry)
    _registry_mod._registry.clear()
    yield
    _registry_mod._registry.clear()
    _registry_mod._registry.update(snapshot)


def _stub(url, anchors=None, **opts):
    return []


class TestRegisterFetcher:
    def test_register_and_get(self):
        register_fetcher("source_a", _stub)
        assert get_fetcher("source_a") is _stub

    def test_register_empty_name_rejected(self):
        with pytest.raises(ValueError):
            register_fetcher("", _stub)

    def test_duplicate_registration_rejected(self):
        register_fetcher("source_a", _stub)
        with pytest.raises(ValueError, match="already registered"):
            register_fetcher("source_a", _stub)

    def test_replace_true_overrides(self):
        def other(url, anchors=None, **opts):
            return []

        register_fetcher("source_a", _stub)
        register_fetcher("source_a", other, replace=True)
        assert get_fetcher("source_a") is other


class TestDecorator:
    def test_decorator_registers(self):
        @register("rss")
        def fetch_feed(url, anchors=None, **opts):
            return []

        assert get_fetcher("rss") is fetch_feed

    def test_decorator_returns_fn_unchanged(self):
        @register("source_b")
        def fn(url, anchors=None, **opts):
            return []

        # Decorator should not wrap; returns same callable
        assert callable(fn)
        assert get_fetcher("source_b") is fn

    def test_decorator_replace(self):
        @register("source_c")
        def first(url, anchors=None, **opts):
            return []

        @register("source_c", replace=True)
        def second(url, anchors=None, **opts):
            return []

        assert get_fetcher("source_c") is second


class TestGetFetcher:
    def test_missing_raises_keyerror(self):
        with pytest.raises(KeyError, match="no fetcher registered"):
            get_fetcher("nope")


class TestListFetchers:
    def test_empty_registry(self):
        assert list_fetchers() == []

    def test_sorted_order(self):
        register_fetcher("c", _stub)
        register_fetcher("a", _stub)
        register_fetcher("b", _stub)
        assert list_fetchers() == ["a", "b", "c"]


class TestFetcherFnType:
    def test_type_alias_importable(self):
        # Just confirm the TypeAlias is defined and importable
        assert FetcherFn is not None
