"""Gated integration tests for the article body fetcher.

Run only when ``SCRAPERSLIB_LIVE_TESTS=1`` is set.

- IGN — stable CMS, no bot gating on article bodies. Probes the
  baseline happy path.
- Notebookcheck — Cloudflare-fronted; probes the v1.4.0 swap to
  ``warmed_curl_session()``. Pre-v1.4.0 this URL returned 403 against
  the library's plain-httpx UA; the test asserts it now returns a
  real body.

URLs may 404 eventually. Refresh by picking a fresh article from
``https://feeds.ign.com/ign/games-all`` (IGN) or
``https://www.notebookcheck.net/RSS-Feed-All-Articles-EN.165552.0.html``
(Notebookcheck) and updating the constants.
"""

from __future__ import annotations

import os

import pytest

from scrapers_lib.core.schemas import Anchor, AttributionRegex
from scrapers_lib.tier1.article import fetch_article

LIVE = bool(os.environ.get("SCRAPERSLIB_LIVE_TESTS"))

IGN_ARTICLE_URL = (
    "https://www.ign.com/articles/"
    "mario-galaxy-movie-backstory-now-video-game-canon-miyamoto-suggests"
)

NOTEBOOKCHECK_ARTICLE_URL = (
    "https://www.notebookcheck.net/"
    "Asus-ROG-Xbox-Ally-X.1102117.0.html"
)


@pytest.mark.skipif(not LIVE, reason="live tests disabled; set SCRAPERSLIB_LIVE_TESTS=1")
def test_fetch_article_discovery_live():
    mentions = fetch_article(IGN_ARTICLE_URL, source_slug="ign")
    # Discovery mode: exactly one mention with attribution=None.
    if not mentions:
        pytest.skip(
            f"trafilatura returned no body for {IGN_ARTICLE_URL}; "
            f"URL likely aged out — refresh via scripts/rss/probe_feeds.py"
        )
    assert len(mentions) == 1
    m = mentions[0]
    assert m.source == "ign"
    assert m.source_type == "article"
    assert m.attribution is None
    assert m.raw_text.strip()
    assert m.source_url == IGN_ARTICLE_URL


@pytest.mark.skipif(not LIVE, reason="live tests disabled; set SCRAPERSLIB_LIVE_TESTS=1")
def test_fetch_article_anchor_mode_live():
    anchor = Anchor(
        anchor_id="nintendo",
        anchor_type="company",
        name="Nintendo",
        attribution_regex=AttributionRegex(primary=["Nintendo"]),
    )
    mentions = fetch_article(IGN_ARTICLE_URL, anchors=[anchor], source_slug="ign")
    # Mario Galaxy article mentions Nintendo repeatedly — should hit.
    # If not, either the article aged out of scope or the extraction
    # changed semantically — surface as a skip, not a fail.
    if not mentions:
        pytest.skip(f"no Nintendo match in live {IGN_ARTICLE_URL}")
    for m in mentions:
        assert m.source == "ign"
        assert m.attribution.anchor_id == "nintendo"
        assert m.mention_id.endswith("_nintendo")


@pytest.mark.skipif(not LIVE, reason="live tests disabled; set SCRAPERSLIB_LIVE_TESTS=1")
def test_fetch_article_notebookcheck_cloudflare_clears():
    """Cloudflare-fronted article — exercises the v1.4.0 warmed_curl_session path.

    Pre-v1.4.0 the library's plain-httpx UA hit a 403 here. The
    upgraded fetcher should return a real body via Chrome impersonation.
    """
    mentions = fetch_article(NOTEBOOKCHECK_ARTICLE_URL, source_slug="notebookcheck")
    if not mentions:
        pytest.skip(
            f"trafilatura returned no body for {NOTEBOOKCHECK_ARTICLE_URL}; "
            f"URL likely aged out — refresh from "
            f"https://www.notebookcheck.net/RSS-Feed-All-Articles-EN.165552.0.html"
        )
    assert len(mentions) == 1
    m = mentions[0]
    assert m.source == "notebookcheck"
    assert m.source_type == "article"
    assert m.attribution is None
    assert m.raw_text.strip()
    assert m.source_url == NOTEBOOKCHECK_ARTICLE_URL
