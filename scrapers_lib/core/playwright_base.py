"""Playwright helpers: fingerprint masking + per-domain persistent profiles.

Provides :func:`stealth_context`, a context manager that yields a Playwright
:class:`Page` with:

- A persistent per-domain Chromium profile (cookies, history, and local
  storage accumulate across fetches — harder to fingerprint over time).
- ``playwright-stealth`` fingerprint-masking (navigator.webdriver override,
  chrome-object spoofing, permissions shim, webgl vendor override, etc.).
- A current Chromium user agent (Wave 1 shipped a stale UA that tripped
  Akamai on dell.com; upgraded in Wave 2a).
- The ``--disable-blink-features=AutomationControlled`` launch flag.

Playwright and ``playwright_stealth`` are imported lazily inside
:func:`stealth_context` so this module can be imported in Tier 1-only
environments.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


DEFAULT_VIEWPORT: tuple[int, int] = (1920, 1080)

# Bump when a new Chromium major ships. Mismatch between the advertised UA
# and the installed Chromium version is a cheap bot signal for WAFs; we
# aim to stay within one major of what ``playwright install chromium``
# actually bundles.
DEFAULT_USER_AGENT: str = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
)

DEFAULT_LOCALE: str = "en-US"

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
    locale: str = DEFAULT_LOCALE,
    launch_args: tuple[str, ...] = DEFAULT_LAUNCH_ARGS,
    use_stealth: bool = True,
) -> Iterator[Any]:
    """Yield a Playwright ``Page`` with fingerprint masking and a persistent profile.

    Imports Playwright lazily; raises :class:`ImportError` if Playwright (or
    ``playwright_stealth`` when ``use_stealth=True``) is not installed. The
    enclosing ``launch_persistent_context`` is closed on exit.

    When ``use_stealth`` is ``True`` (the default), ``playwright_stealth``
    instruments the Playwright instance so every context inherits the
    fingerprint evasions. Set to ``False`` for a persistent-profile context
    without stealth — useful for local development or sites that do not
    have bot detection.

    The ``navigator.userAgent`` override matches ``user_agent`` so the
    advertised UA and the stealth-applied UA stay consistent.

    Usage::

        with stealth_context(profiles_dir="./.profiles", domain="dell.com") as page:
            page.goto("https://www.dell.com/xps-15")
            html = page.content()
    """
    # Lazy imports: keeps core library import-able without Playwright.
    from playwright.sync_api import sync_playwright  # noqa: I001

    profile_dir = BrowserProfile(profiles_dir).path_for(domain)

    if use_stealth:
        from playwright_stealth import Stealth  # noqa: I001

        stealth = Stealth(navigator_user_agent_override=user_agent)
        pw_cm: Any = stealth.use_sync(sync_playwright())
    else:
        pw_cm = sync_playwright()

    with pw_cm as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=headless,
            viewport={"width": viewport[0], "height": viewport[1]},
            user_agent=user_agent,
            locale=locale,
            args=list(launch_args),
        )
        page = context.new_page()
        try:
            yield page
        finally:
            context.close()
