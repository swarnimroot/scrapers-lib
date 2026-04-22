"""Unit tests for scrapers_lib.core.playwright_base (pure-Python parts only).

The ``stealth_context`` context manager is integration-only and tested when
Tier 2/3 fetchers exercise it.
"""

from scrapers_lib.core.playwright_base import BrowserProfile, _safe_domain


class TestSafeDomain:
    def test_plain_domain(self):
        assert _safe_domain("example.com") == "example.com"

    def test_strips_https_scheme(self):
        assert _safe_domain("https://example.com") == "example.com"

    def test_strips_http_scheme(self):
        assert _safe_domain("http://example.com") == "example.com"

    def test_replaces_colons(self):
        assert _safe_domain("example.com:8080") == "example.com_8080"

    def test_replaces_slashes(self):
        assert _safe_domain("example.com/path") == "example.com_path"

    def test_replaces_backslashes(self):
        assert _safe_domain("a\\b") == "a_b"

    def test_empty_becomes_default(self):
        assert _safe_domain("") == "_default"


class TestBrowserProfile:
    def test_creates_root_dir(self, tmp_path):
        root = tmp_path / "profiles"
        assert not root.exists()
        BrowserProfile(root)
        assert root.exists()
        assert root.is_dir()

    def test_path_for_creates_subdir(self, tmp_path):
        profiles = BrowserProfile(tmp_path / "profiles")
        p = profiles.path_for("amazon.com")
        assert p.exists()
        assert p.is_dir()
        assert p.name == "amazon.com"
        assert p.parent == (tmp_path / "profiles")

    def test_path_for_sanitizes_scheme(self, tmp_path):
        profiles = BrowserProfile(tmp_path / "profiles")
        p = profiles.path_for("https://amazon.com")
        assert p.name == "amazon.com"

    def test_path_for_sanitizes_special_chars(self, tmp_path):
        profiles = BrowserProfile(tmp_path / "profiles")
        p = profiles.path_for("https://amazon.com:443/foo")
        assert ":" not in p.name
        assert "/" not in p.name
        assert p.exists()

    def test_path_for_reuses_existing(self, tmp_path):
        profiles = BrowserProfile(tmp_path / "profiles")
        p1 = profiles.path_for("example.com")
        p2 = profiles.path_for("example.com")
        assert p1 == p2

    def test_root_property(self, tmp_path):
        root = tmp_path / "profiles"
        profiles = BrowserProfile(root)
        assert profiles.root == root

    def test_different_domains_get_different_dirs(self, tmp_path):
        profiles = BrowserProfile(tmp_path / "profiles")
        a = profiles.path_for("amazon.com")
        b = profiles.path_for("bestbuy.com")
        assert a != b


class TestStealthContextImport:
    def test_module_importable_without_playwright(self):
        """The module should import even if Playwright isn't installed.

        Only the ``stealth_context`` call fails at runtime when Playwright
        is missing; module-level imports should succeed.
        """
        from scrapers_lib.core import playwright_base
        assert hasattr(playwright_base, "stealth_context")
        assert hasattr(playwright_base, "BrowserProfile")
        assert hasattr(playwright_base, "DEFAULT_USER_AGENT")
