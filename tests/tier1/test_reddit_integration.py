"""Gated integration test for the Reddit fetcher.

Runs only when ``SCRAPERSLIB_LIVE_TESTS=1`` is set. Hits
``reddit.com/r/Games/new.json`` unauthenticated with a descriptive
User-Agent. Reddit's JSON endpoints currently tolerate this at
~60 req/min per UA without OAuth — this test is the canary that
verifies they still do.

Reddit has been progressively restricting these endpoints. If this
test starts returning 403 / 429, the ``project_reddit_api_blocked``
memory may need updating and we may need to revisit the fetcher's
I/O strategy.
"""

from __future__ import annotations

import os

import pytest

from scrapers_lib.core.schemas import Anchor, AttributionRegex
from scrapers_lib.tier1.reddit import fetch_reddit_comments, fetch_reddit_listing

LIVE = bool(os.environ.get("SCRAPERSLIB_LIVE_TESTS"))


@pytest.mark.skipif(not LIVE, reason="live tests disabled; set SCRAPERSLIB_LIVE_TESTS=1")
def test_fetch_subreddit_listing_live():
    mentions = fetch_reddit_listing("r/Games", sort="new", limit=10)
    assert len(mentions) >= 5, (
        f"expected >= 5 posts; got {len(mentions)} — "
        "Reddit endpoint may have changed"
    )
    for m in mentions:
        assert m.source == "reddit"
        assert m.source_type == "post"
        assert m.channel == "r/Games"
        assert m.mention_id.startswith("reddit_post_")
        assert m.source_url.startswith("https://www.reddit.com")
        assert m.raw_text.strip()
        assert m.attribution is None


@pytest.mark.skipif(not LIVE, reason="live tests disabled; set SCRAPERSLIB_LIVE_TESTS=1")
def test_fetch_post_comments_live():
    # Grab the first post from r/Games and fetch its comments.
    listing = fetch_reddit_listing("r/Games", sort="hot", limit=5)
    assert listing, "empty listing — cannot identify a post to test comments against"
    post_url = listing[0].source_url
    bundle = fetch_reddit_comments(post_url)
    # The post itself must lead the bundle; at least one comment usually exists
    # on a "hot" post but some fresh hot posts have zero comments.
    assert bundle, "no mentions returned from comments endpoint"
    assert bundle[0].source_type == "post"
    post_fullname = f"t3_{bundle[0].raw['post_id']}"
    for m in bundle[1:]:
        assert m.source_type == "comment"
        assert m.parent_id == post_fullname
        assert m.raw_text.strip()


@pytest.mark.skipif(not LIVE, reason="live tests disabled; set SCRAPERSLIB_LIVE_TESTS=1")
def test_anchor_mode_live():
    # Generic anchor that any large gaming sub will hit occasionally.
    anchor = Anchor(
        anchor_id="nintendo",
        anchor_type="company",
        name="Nintendo",
        attribution_regex=AttributionRegex(primary=["Nintendo"]),
    )
    mentions = fetch_reddit_listing(
        "r/Games", sort="new", limit=50, anchors=[anchor]
    )
    # 0 is acceptable (some snapshots have no Nintendo posts); asserting
    # the shape of whatever DOES come back is what matters.
    for m in mentions:
        assert m.attribution is not None
        assert m.attribution.anchor_id == "nintendo"
        assert m.mention_id.endswith("_nintendo")
