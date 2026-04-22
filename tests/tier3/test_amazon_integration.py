"""Gated integration test for the Amazon fetcher.

Runs only when ``SCRAPERSLIB_LIVE_TESTS=1`` is set; otherwise skipped so
the default ``pytest`` run does not hit the network. Fetches one real
Amazon PDP via plain httpx and verifies the full pipeline produces one
:class:`ProductSnapshot` with rich structured specs, plus at least one
:class:`RawMention` from the inlined reviews.
"""

from __future__ import annotations

import os

import pytest

from scrapers_lib.core.schemas import Anchor, AttributionRegex
from scrapers_lib.tier3.amazon import fetch_amazon_product, fetch_amazon_reviews

LIVE = bool(os.environ.get("SCRAPERSLIB_LIVE_TESTS"))

# ASIN chosen to exercise the standard bylineInfo + prodDetTable PDP
# shape. If the listing gets retired, refresh by re-running
# ``scripts/amazon/probe_posture.py`` against a current gaming-laptop
# search page and picking a fresh ASIN.
ALIENWARE_URL = "https://www.amazon.com/dp/B0F8P6MRQT"


@pytest.mark.skipif(not LIVE, reason="live tests disabled; set SCRAPERSLIB_LIVE_TESTS=1")
def test_fetch_alienware_area_51_live():
    anchor = Anchor(
        anchor_id="alienware_area_51",
        anchor_type="product",
        name="Alienware 16 Area-51",
        attribution_regex=AttributionRegex(primary=["Alienware", "Area-51"]),
        source_urls={"amazon": ALIENWARE_URL},
    )

    snapshots = fetch_amazon_product(ALIENWARE_URL, anchors=[anchor])

    assert len(snapshots) == 1
    s = snapshots[0]
    assert s.source == "amazon"
    assert s.anchor_id == anchor.anchor_id
    assert s.source_id == "B0F8P6MRQT"
    assert s.url == ALIENWARE_URL
    assert s.title
    assert s.raw["spec_source"] == "prodDetTable"

    # An active gaming-laptop PDP should have a price, a rating, and at
    # least a handful of prodDetTable spec rows.
    assert s.price is None or s.price > 0
    assert s.rating is None or 0 <= s.rating <= 5
    assert len(s.specs) >= 20, f"only {len(s.specs)} specs returned"

    mentions = fetch_amazon_reviews(ALIENWARE_URL, anchors=[anchor])
    assert len(mentions) >= 1, "expected at least one inlined review"
    for m in mentions:
        assert m.source == "amazon"
        assert m.attribution.anchor_id == anchor.anchor_id
        assert m.raw_text.strip()
        assert m.parent_id == "B0F8P6MRQT"
