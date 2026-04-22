"""Playwright helpers: basic stealth tweaks + per-domain persistent profiles.

Ships a minimal set of anti-automation tweaks (realistic user agent,
realistic viewport, the ``--disable-blink-features=AutomationControlled``
launch flag) plus per-domain persistent Chromium profiles so cookies,
history, and local storage accumulate across fetches — harder to
fingerprint over time.

Heavier fingerprint evasion can be layered on by callers via
``playwright-stealth`` or similar; this module stays dependency-light.

Playwright is imported lazily inside :func:`stealth_context` so this
module can be imported in environments that use only Tier 1 sources
(no browser automation needed).
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


DEFAULT_VIEWPORT: tuple[int, int] = (1920, 1080)

DEFAULT_USER_AGENT: str = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

DEFAULT_LAUNCH_ARGS: tuple[str, ...] = (
    "--disable-blink-features=AutomationControlled",
    "--disable-dev-shm-usage",
)


class BrowserProfile:
    """Manages per-domain persistent Playwright profile directories.

    Each domain gets its own subdirectory so session state (cookies, history,
    local storage) accumulates across fetches. This is consumer-owned state;
    the directory is created lazily on first use.
    """

    def __init__(self, profiles_dir: str | Path) -> None:
        self._profiles_dir = Path(profiles_dir)
        self._profiles_dir.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._profiles_dir

    def path_for(self, domain: str) -> Path:
        """Return the profile directory for ``domain`` (create if missing)."""
        safe = _safe_domain(domain)
        p = self._profiles_dir / safe
        p.mkdir(parents=True, exist_ok=True)
        return p


def _safe_domain(domain: str) -> str:
    """Sanitize ``domain`` into a safe directory name."""
    s = domain.replace("https://", "").replace("http://", "")
    s = s.replace(":", "_").replace("/", "_").replace("\\", "_")
    return s or "_default"


@contextmanager
def stealth_context(
    *,
    profiles_dir: str | Path,
    domain: str,
    headless: bool = True,
    viewport: tuple[int, int] = DEFAULT_VIEWPORT,
    user_agent: str = DEFAULT_USER_AGENT,
    launch_args: tuple[str, ...] = DEFAULT_LAUNCH_ARGS,
) -> Iterator[Any]:
    """Yield a Playwright ``Page`` with stealth tweaks and a persistent profile.

    Imports Playwright lazily; raises :class:`ImportError` if Playwright is
    not installed. The enclosing ``launch_persistent_context`` is closed on
    exit.

    Usage::

        with stealth_context(profiles_dir="./.profiles", domain="dell.com") as page:
            page.goto("https://www.dell.com/xps-15")
            html = page.content()
    """
    # Lazy import: keeps core library import-able without Playwright.
    from playwright.sync_api import sync_playwright  # noqa: I001

    profile_dir = BrowserProfile(profiles_dir).path_for(domain)

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=headless,
            viewport={"width": viewport[0], "height": viewport[1]},
            user_agent=user_agent,
            args=list(launch_args),
        )
        page = context.new_page()
        try:
            yield page
        finally:
            context.close()
