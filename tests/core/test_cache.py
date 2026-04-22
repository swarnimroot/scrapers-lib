"""Unit tests for scrapers_lib.core.cache."""

import time

import pytest

from scrapers_lib.core.cache import Cache, DEFAULT_TTLS


@pytest.fixture
def cache(tmp_path):
    c = Cache(tmp_path / "cache")
    yield c
    c.close()


class TestMakeKey:
    def test_basic_key(self):
        k = Cache.make_key("rss", "https://example.com/feed")
        assert k == "rss|https://example.com/feed"

    def test_extra_kwargs_included_sorted(self):
        k = Cache.make_key("rss", "https://x.com", page=2, sort="new")
        assert k == "rss|https://x.com|page=2|sort=new"

    def test_same_inputs_give_same_key(self):
        k1 = Cache.make_key("rss", "https://x.com", page=1)
        k2 = Cache.make_key("rss", "https://x.com", page=1)
        assert k1 == k2

    def test_extra_kwarg_order_independent(self):
        k1 = Cache.make_key("rss", "u", a=1, b=2)
        k2 = Cache.make_key("rss", "u", b=2, a=1)
        assert k1 == k2


class TestBasicOps:
    def test_get_missing_returns_none(self, cache):
        assert cache.get("missing") is None

    def test_get_missing_returns_default(self, cache):
        assert cache.get("missing", default="fallback") == "fallback"

    def test_set_then_get(self, cache):
        cache.set("k1", {"foo": 1})
        assert cache.get("k1") == {"foo": 1}

    def test_delete(self, cache):
        cache.set("k", "v")
        assert cache.delete("k") is True
        assert cache.get("k") is None

    def test_delete_missing_returns_false(self, cache):
        assert cache.delete("nope") is False

    def test_clear(self, cache):
        cache.set("a", 1)
        cache.set("b", 2)
        cache.clear()
        assert cache.get("a") is None
        assert cache.get("b") is None


class TestTTL:
    def test_explicit_ttl_takes_precedence(self, cache):
        cache.set("k", "v", source="reddit", ttl=1)
        assert cache.get("k") == "v"
        time.sleep(1.2)
        assert cache.get("k") is None

    def test_source_default_ttl_applied(self, tmp_path):
        # Override 'reddit' to a tiny TTL so we can test expiry quickly
        cache = Cache(tmp_path / "cache", ttls={"reddit": 1})
        cache.set("k", "v", source="reddit")
        assert cache.get("k") == "v"
        time.sleep(1.2)
        assert cache.get("k") is None
        cache.close()

    def test_no_source_no_ttl_persists(self, cache):
        cache.set("k", "v")
        assert cache.get("k") == "v"
        # No way to cleanly test "forever" in a unit test; just confirm
        # the value is present immediately.

    def test_unknown_source_has_no_default_ttl(self, cache):
        cache.set("k", "v", source="unknown_source")
        assert cache.get("k") == "v"


class TestDefaults:
    def test_default_ttls_exist_for_known_sources(self):
        for source in ("reddit", "rss", "amazon", "dell"):
            assert source in DEFAULT_TTLS
            assert DEFAULT_TTLS[source] > 0

    def test_retail_reviews_longer_than_prices(self):
        # Reviews change slowly; prices change daily
        assert DEFAULT_TTLS["amazon"] > DEFAULT_TTLS["bestbuy_api"]


class TestContextManager:
    def test_context_manager_closes(self, tmp_path):
        with Cache(tmp_path / "cache") as c:
            c.set("k", "v")
            assert c.get("k") == "v"
