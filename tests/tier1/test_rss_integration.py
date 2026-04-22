"""Gated integration test for the RSS feed fetcher.

Runs only when ``SCRAPERSLIB_LIVE_TESTS=1`` is set. Fetches IGN's
games feed (picked for stability — large catalog, consistent shape)
and verifies the fetcher produces valid :class:`RawMention` objects
in both discovery and anchor-driven modes.

The feed URL may change if IGN redesigns their RSS infrastructure;
refresh by re-running ``scripts/rss/probe_feeds.py`` and updating.
"""

from __future__ import annotations

import os

import pytest

from scrapers_lib.core.schemas import Anchor, AttributionRegex
from scrapers_lib.tier1.rss import fetch_rss_feed

LIVE = bool(os.environ.get("SCRAPERSLIB_LIVE_TESTS"))

IGN_GAMES_FEED = "https://feeds.ign.com/ign/games-all"


@pytest.mark.skipif(not LIVE, reason="live tests disabled; set SCRAPERSLIB_LIVE_TESTS=1")
def test_fetch_ign_discovery_mode_live():
    mentions = fetch_rss_feed(IGN_GAMES_FEED, source_slug="ign")
    assert len(mentions) >= 5, (
        f"expected at least 5 entries in IGN feed, got {len(mentions)}; "
        f"URL may have changed — refresh via scripts/rss/probe_feeds.py"
    )
    for m in mentions:
        assert m.source == "ign"
        assert m.source_type == "article"
        assert m.source_url.startswith("http")
        assert m.raw_text.strip()
        assert m.attribution is None
    # Deterministic mention_id should survive a re-fetch.
    again = fetch_rss_feed(IGN_GAMES_FEED, source_slug="ign")
    first_ids = {m.mention_id for m in mentions}
    second_ids = {m.mention_id for m in again}
    # Freshest-item IDs might roll over between calls, but the bulk of the
    # older entries should still share IDs — require at least 50% overlap.
    overlap = first_ids & second_ids
    assert len(overlap) >= len(first_ids) // 2, (
        "mention_id did not stay stable across re-fetches of the same feed"
    )


@pytest.mark.skipif(not LIVE, reason="live tests disabled; set SCRAPERSLIB_LIVE_TESTS=1")
def test_fetch_ign_anchor_mode_live():
    # A topical anchor likely to match at least one IGN games entry on any
    # given day. If this starts failing, replace with a fresher topic — it
    # is a sanity check, not a semantic claim about "Nintendo" in perpetuity.
    anchor = Anchor(
        anchor_id="nintendo",
        anchor_type="company",
        name="Nintendo",
        attribution_regex=AttributionRegex(primary=["Nintendo"]),
    )
    mentions = fetch_rss_feed(IGN_GAMES_FEED, anchors=[anchor], source_slug="ign")
    # We do not assert on count — some days the feed has zero Nintendo
    # mentions — but what DOES come through must be properly attributed.
    for m in mentions:
        assert m.attribution is not None
        assert m.attribution.anchor_id == "nintendo"
        assert m.mention_id.endswith("_nintendo")
