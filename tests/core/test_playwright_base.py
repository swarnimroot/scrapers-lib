"""Unit tests for scrapers_lib.core.playwright_base (pure-Python parts only).

The ``stealth_context`` context manager is integration-only and tested when
Tier 2/3 fetchers exercise it.
"""

import inspect
import re

from scrapers_lib.core.playwright_base import (
    DEFAULT_LOCALE,
    DEFAULT_USER_AGENT,
    BrowserProfile,
    _safe_domain,
    stealth_context,
)


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


class TestDefaultUserAgent:
    def test_chrome_major_is_current(self):
        # Regression guard: Wave 1 shipped Chrome/124 which tripped Akamai.
        # Bump together with the Chromium install when Chromium itself moves
        # to a new major.
        m = re.search(r"Chrome/(\d+)", DEFAULT_USER_AGENT)
        assert m is not None, f"no Chrome major in UA: {DEFAULT_USER_AGENT!r}"
        assert int(m.group(1)) >= 145

    def test_ua_is_windows_chrome(self):
        assert "Windows NT 10.0" in DEFAULT_USER_AGENT
        assert "Safari/537.36" in DEFAULT_USER_AGENT


class TestStealthContextSignature:
    def test_accepts_use_stealth_kwarg(self):
        sig = inspect.signature(stealth_context)
        assert "use_stealth" in sig.parameters
        assert sig.parameters["use_stealth"].default is True

    def test_accepts_locale_kwarg(self):
        sig = inspect.signature(stealth_context)
        assert "locale" in sig.parameters
        assert sig.parameters["locale"].default == DEFAULT_LOCALE

    def test_profiles_dir_and_domain_required(self):
        sig = inspect.signature(stealth_context)
        # Both must be keyword-only with no default (required).
        for name in ("profiles_dir", "domain"):
            assert name in sig.parameters
            assert sig.parameters[name].kind == inspect.Parameter.KEYWORD_ONLY
            assert sig.parameters[name].default is inspect.Parameter.empty
