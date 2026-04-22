"""Unit tests for scrapers_lib.core.rate_limiter."""

import pytest

from scrapers_lib.core.rate_limiter import Bucket, RateLimiter


class TestBucket:
    def test_starts_full(self):
        b = Bucket(capacity=3.0, refill_per_sec=1.0)
        assert b.tokens == 3.0

    def test_acquire_when_tokens_available(self):
        b = Bucket(capacity=2.0, refill_per_sec=1.0)
        assert b.try_acquire(now=100.0) is True
        assert b.try_acquire(now=100.0) is True

    def test_acquire_fails_when_empty(self):
        b = Bucket(capacity=1.0, refill_per_sec=1.0)
        assert b.try_acquire(now=100.0) is True
        assert b.try_acquire(now=100.0) is False

    def test_refill_over_time(self):
        b = Bucket(capacity=2.0, refill_per_sec=1.0)
        # Drain
        b.try_acquire(now=100.0)
        b.try_acquire(now=100.0)
        assert b.try_acquire(now=100.0) is False
        # Wait 1 second → 1 token refilled
        assert b.try_acquire(now=101.0) is True
        assert b.try_acquire(now=101.0) is False

    def test_refill_capped_at_capacity(self):
        b = Bucket(capacity=2.0, refill_per_sec=1.0)
        b.try_acquire(now=100.0)
        # Wait a long time; should only refill to capacity
        assert b.try_acquire(now=1000.0) is True
        assert b.try_acquire(now=1000.0) is True
        assert b.try_acquire(now=1000.0) is False

    def test_wait_seconds_zero_when_token_available(self):
        b = Bucket(capacity=1.0, refill_per_sec=1.0)
        assert b.wait_seconds(now=100.0) == 0.0

    def test_wait_seconds_positive_when_empty(self):
        b = Bucket(capacity=1.0, refill_per_sec=2.0)  # 2 tokens/sec
        b.try_acquire(now=100.0)
        # Empty; next token in 0.5s
        assert b.wait_seconds(now=100.0) == pytest.approx(0.5, abs=0.01)

    def test_wait_seconds_infinite_when_no_refill(self):
        b = Bucket(capacity=1.0, refill_per_sec=0.0)
        b.try_acquire(now=100.0)
        assert b.wait_seconds(now=100.0) == float("inf")


class TestRateLimiter:
    def test_default_domain_gets_default_bucket(self):
        rl = RateLimiter(default_rps=5.0, default_burst=1)
        # First call should succeed (default_burst=1)
        assert rl.try_acquire("example.com") is True
        # Second call immediately should fail (burst exhausted)
        assert rl.try_acquire("example.com") is False

    def test_configure_sets_custom_bucket(self):
        rl = RateLimiter()
        rl.configure("amazon.com", rps=1.0, burst=5)
        # Burst of 5: five acquires in a row should succeed
        for _ in range(5):
            assert rl.try_acquire("amazon.com") is True
        assert rl.try_acquire("amazon.com") is False

    def test_different_domains_have_independent_buckets(self):
        rl = RateLimiter(default_rps=1.0, default_burst=1)
        assert rl.try_acquire("a.com") is True
        # Other domain unaffected
        assert rl.try_acquire("b.com") is True
        # Original still empty
        assert rl.try_acquire("a.com") is False

    def test_reconfigure_replaces_bucket(self):
        rl = RateLimiter()
        rl.configure("example.com", rps=1.0, burst=1)
        rl.try_acquire("example.com")
        assert rl.try_acquire("example.com") is False
        # Reconfigure with bigger burst — bucket resets to full
        rl.configure("example.com", rps=1.0, burst=3)
        for _ in range(3):
            assert rl.try_acquire("example.com") is True

    def test_invalid_rps_rejected(self):
        rl = RateLimiter()
        with pytest.raises(ValueError):
            rl.configure("x", rps=0)
        with pytest.raises(ValueError):
            rl.configure("x", rps=-1)

    def test_invalid_burst_rejected(self):
        rl = RateLimiter()
        with pytest.raises(ValueError):
            rl.configure("x", rps=1.0, burst=0)

    def test_wait_seconds_for_fresh_domain_is_zero(self):
        rl = RateLimiter(default_rps=1.0, default_burst=1)
        assert rl.wait_seconds("new-domain.com") == 0.0
