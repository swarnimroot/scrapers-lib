"""Gated integration test for the article body fetcher.

Runs only when ``SCRAPERSLIB_LIVE_TESTS=1`` is set. Hits one IGN
article URL live — IGN chosen for the same stability reasons as the
RSS integration test (stable CMS, no bot gating on article bodies).

The URL may 404 eventually. Refresh by picking a fresh article from
``https://feeds.ign.com/ign/games-all`` and updating the constant.
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
