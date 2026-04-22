"""Unit tests for scrapers_lib.core.http_client."""

import httpx
import pytest

from scrapers_lib.core.http_client import DEFAULT_USER_AGENTS, HttpClient


class _CountingSleep:
    """Records sleep durations without actually sleeping."""

    def __init__(self) -> None:
        self.calls: list[float] = []

    def __call__(self, duration: float) -> None:
        self.calls.append(duration)


def _make_client(handler, *, max_retries: int = 3, backoff_base: float = 0.1):
    """Build an HttpClient backed by an httpx MockTransport and a no-sleep fn."""
    sleeper = _CountingSleep()
    client = HttpClient(
        transport=httpx.MockTransport(handler),
        sleep_fn=sleeper,
        max_retries=max_retries,
        backoff_base=backoff_base,
    )
    return client, sleeper


class TestSuccess:
    def test_200_returned_directly(self):
        def handler(request):
            return httpx.Response(200, text="ok")

        client, sleeper = _make_client(handler)
        resp = client.get("https://example.com/x")
        assert resp.status_code == 200
        assert resp.text == "ok"
        assert sleeper.calls == []
        client.close()

    def test_user_agent_header_added(self):
        captured: dict[str, str] = {}

        def handler(request):
            captured["ua"] = request.headers.get("user-agent", "")
            return httpx.Response(200, text="")

        client, _ = _make_client(handler)
        client.get("https://example.com/x")
        assert captured["ua"] in DEFAULT_USER_AGENTS
        client.close()

    def test_custom_headers_merged(self):
        captured: dict[str, str] = {}

        def handler(request):
            for k, v in request.headers.items():
                captured[k] = v
            return httpx.Response(200)

        client, _ = _make_client(handler)
        client.get("https://example.com/x", headers={"X-Custom": "foo"})
        assert captured.get("x-custom") == "foo"
        # UA still set
        assert "user-agent" in captured
        client.close()


class TestRetryOn429:
    def test_retries_then_succeeds(self):
        attempts = {"n": 0}

        def handler(request):
            attempts["n"] += 1
            if attempts["n"] <= 2:
                return httpx.Response(429, headers={"Retry-After": "0"})
            return httpx.Response(200, text="ok")

        client, sleeper = _make_client(handler, max_retries=3)
        resp = client.get("https://example.com/x")
        assert resp.status_code == 200
        assert attempts["n"] == 3
        # Two sleeps between three attempts
        assert len(sleeper.calls) == 2
        client.close()

    def test_respects_retry_after_header(self):
        attempts = {"n": 0}

        def handler(request):
            attempts["n"] += 1
            if attempts["n"] == 1:
                return httpx.Response(429, headers={"Retry-After": "5"})
            return httpx.Response(200)

        client, sleeper = _make_client(handler)
        client.get("https://example.com/x")
        # First sleep should be ~5 seconds (Retry-After)
        assert sleeper.calls[0] == 5.0
        client.close()

    def test_exhausts_retries_returns_last_response(self):
        def handler(request):
            return httpx.Response(429, headers={"Retry-After": "0"})

        client, _ = _make_client(handler, max_retries=2)
        resp = client.get("https://example.com/x")
        # After max_retries + 1 attempts, return the last 429
        assert resp.status_code == 429
        client.close()


class TestRetryOn503:
    def test_retries_then_succeeds(self):
        attempts = {"n": 0}

        def handler(request):
            attempts["n"] += 1
            if attempts["n"] == 1:
                return httpx.Response(503)
            return httpx.Response(200, text="ok")

        client, _ = _make_client(handler)
        resp = client.get("https://example.com/x")
        assert resp.status_code == 200
        assert attempts["n"] == 2
        client.close()


class TestRetryOnNetworkError:
    def test_retries_then_succeeds(self):
        attempts = {"n": 0}

        def handler(request):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise httpx.ConnectError("boom")
            return httpx.Response(200, text="ok")

        client, _ = _make_client(handler, max_retries=3)
        resp = client.get("https://example.com/x")
        assert resp.status_code == 200
        assert attempts["n"] == 2
        client.close()

    def test_exhausts_retries_reraises(self):
        def handler(request):
            raise httpx.ConnectError("boom")

        client, _ = _make_client(handler, max_retries=2)
        with pytest.raises(httpx.ConnectError):
            client.get("https://example.com/x")
        client.close()


class TestNoRetryOn4xx:
    def test_404_returned_immediately(self):
        attempts = {"n": 0}

        def handler(request):
            attempts["n"] += 1
            return httpx.Response(404)

        client, sleeper = _make_client(handler)
        resp = client.get("https://example.com/x")
        assert resp.status_code == 404
        assert attempts["n"] == 1
        assert sleeper.calls == []
        client.close()

    def test_500_returned_immediately(self):
        """500 is not in our retry set (429/503 only); returned as-is."""
        attempts = {"n": 0}

        def handler(request):
            attempts["n"] += 1
            return httpx.Response(500)

        client, _ = _make_client(handler)
        resp = client.get("https://example.com/x")
        assert resp.status_code == 500
        assert attempts["n"] == 1
        client.close()


class TestContextManager:
    def test_context_manager_closes(self):
        def handler(request):
            return httpx.Response(200)

        with _make_client(handler)[0] as client:
            resp = client.get("https://example.com/x")
            assert resp.status_code == 200
