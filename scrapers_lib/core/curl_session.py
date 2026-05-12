"""Warmed curl_cffi session helper (Akamai / CDN HTTP/2 RST-stream + Cloudflare bypass).

Graduated from ``scrapers_lib.tier2.base`` in v1.4.0 — the helper is now
reused across tiers (Tier 1 article fetch, Tier 2 HP/MSI, Tier 3 BestBuy)
so it lives in ``core/`` rather than under a specific tier. The previous
import path (``from scrapers_lib.tier2.base import warmed_curl_session``)
continues to work via a re-export shim in ``tier2/base``.

``curl_cffi`` is imported lazily inside the context manager so
``import scrapers_lib`` stays cheap for consumers that never touch a
Cloudflare- or Akamai-gated source.
"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Iterator, TYPE_CHECKING

if TYPE_CHECKING:
    from curl_cffi.requests import Session

logger = logging.getLogger(__name__)


@contextmanager
def warmed_curl_session(
    homepage: str,
    *,
    impersonate: str = "chrome",
    warm: bool = True,
    warm_delay: float = 1.0,
    warm_headers: dict[str, str] | None = None,
    timeout: float = 30.0,
) -> Iterator["Session"]:
    """Context manager yielding a warmed curl_cffi Session.

    Creates a curl_cffi Session with Chrome TLS impersonation + HTTP/1.1
    (Akamai HTTP/2 RST-stream gate workaround; also clears Cloudflare's
    UA-based article gates). When ``warm=True``, fires a homepage GET and
    sleeps ``warm_delay`` seconds before yielding so cookies settle.
    Warm-up failures are swallowed and logged at DEBUG.

    Used by Tier 1 (article body), Tier 2 (HP, MSI), and Tier 3 (BestBuy)
    to clear Akamai/CDN/Cloudflare gates that reject plain httpx.
    """
    from curl_cffi import CurlHttpVersion, requests  # noqa: I001

    with requests.Session(
        impersonate=impersonate,
        http_version=CurlHttpVersion.V1_1,
    ) as s:
        if warm:
            try:
                if warm_headers is not None:
                    s.get(homepage, headers=warm_headers, timeout=timeout)
                else:
                    s.get(homepage, timeout=timeout)
                time.sleep(warm_delay)
            except Exception as e:  # pragma: no cover - warming best-effort
                logger.debug(
                    "warmed_curl_session(%s): warm failed: %s", homepage, e
                )
        yield s
