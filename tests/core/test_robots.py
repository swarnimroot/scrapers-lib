"""Unit tests for scrapers_lib.core.robots."""

from scrapers_lib.core.robots import RobotsChecker


def _make_fetch(responses: dict[str, tuple[int, str]]):
    """Build a fetch_fn that returns canned (status, body) per URL."""
    calls: list[str] = []

    def fetch(url: str, user_agent: str) -> tuple[int, str]:
        calls.append(url)
        if url in responses:
            return responses[url]
        return (404, "")

    fetch.calls = calls  # type: ignore[attr-defined]
    return fetch


class TestRobotsChecker:
    def test_missing_robots_txt_means_allow(self):
        fetch = _make_fetch({})  # 404 for everything
        checker = RobotsChecker(fetch_fn=fetch)
        assert checker.allowed("https://example.com/anything") is True

    def test_empty_robots_txt_means_allow(self):
        fetch = _make_fetch({"https://example.com/robots.txt": (200, "")})
        checker = RobotsChecker(fetch_fn=fetch)
        assert checker.allowed("https://example.com/anything") is True

    def test_disallow_all_blocks(self):
        robots = "User-agent: *\nDisallow: /\n"
        fetch = _make_fetch({"https://example.com/robots.txt": (200, robots)})
        checker = RobotsChecker(fetch_fn=fetch)
        assert checker.allowed("https://example.com/page") is False

    def test_disallow_specific_path(self):
        robots = "User-agent: *\nDisallow: /private/\n"
        fetch = _make_fetch({"https://example.com/robots.txt": (200, robots)})
        checker = RobotsChecker(fetch_fn=fetch)
        assert checker.allowed("https://example.com/public") is True
        assert checker.allowed("https://example.com/private/x") is False

    def test_allow_specific_subpath(self):
        # Python's urllib.robotparser uses first-match-wins rule order (not
        # Google-style longest-match). So Allow must precede Disallow when
        # the allow is a subpath of the disallow.
        robots = (
            "User-agent: *\n"
            "Allow: /private/public-announcement\n"
            "Disallow: /private/\n"
        )
        fetch = _make_fetch({"https://example.com/robots.txt": (200, robots)})
        checker = RobotsChecker(fetch_fn=fetch)
        assert checker.allowed("https://example.com/private/secret") is False
        assert checker.allowed(
            "https://example.com/private/public-announcement"
        ) is True

    def test_specific_user_agent_rules(self):
        robots = (
            "User-agent: badbot\nDisallow: /\n\nUser-agent: *\nDisallow:\n"
        )
        fetch = _make_fetch({"https://example.com/robots.txt": (200, robots)})
        good = RobotsChecker(user_agent="goodbot", fetch_fn=fetch)
        bad = RobotsChecker(user_agent="badbot", fetch_fn=fetch)
        assert good.allowed("https://example.com/anything") is True
        assert bad.allowed("https://example.com/anything") is False

    def test_fetch_error_means_allow(self):
        def failing_fetch(url: str, ua: str):
            raise ConnectionError("boom")

        checker = RobotsChecker(fetch_fn=failing_fetch)
        assert checker.allowed("https://example.com/anything") is True

    def test_5xx_means_allow(self):
        fetch = _make_fetch({"https://example.com/robots.txt": (503, "")})
        checker = RobotsChecker(fetch_fn=fetch)
        assert checker.allowed("https://example.com/page") is True

    def test_malformed_url_means_allow(self):
        checker = RobotsChecker(fetch_fn=_make_fetch({}))
        # No scheme/netloc — nothing to check
        assert checker.allowed("not-a-url") is True
        assert checker.allowed("") is True

    def test_robots_cached_per_origin(self):
        robots = "User-agent: *\nDisallow:\n"
        fetch = _make_fetch({"https://example.com/robots.txt": (200, robots)})
        checker = RobotsChecker(fetch_fn=fetch)
        checker.allowed("https://example.com/a")
        checker.allowed("https://example.com/b")
        checker.allowed("https://example.com/c")
        # Fetched robots.txt only once
        assert fetch.calls.count("https://example.com/robots.txt") == 1  # type: ignore[attr-defined]

    def test_different_origins_fetched_separately(self):
        robots_a = "User-agent: *\nDisallow: /\n"
        robots_b = "User-agent: *\nDisallow:\n"
        fetch = _make_fetch(
            {
                "https://a.com/robots.txt": (200, robots_a),
                "https://b.com/robots.txt": (200, robots_b),
            }
        )
        checker = RobotsChecker(fetch_fn=fetch)
        assert checker.allowed("https://a.com/x") is False
        assert checker.allowed("https://b.com/x") is True
