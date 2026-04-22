"""Gated integration test for the BestBuy reviews fetcher.

Runs only when ``SCRAPERSLIB_LIVE_TESTS=1`` is set; otherwise skipped
so the default ``pytest`` run does not hit the network. Uses the
curl_cffi + Chrome impersonation + HTTP/1.1 primitive to fetch a real
BestBuy PDP and verifies the inline JSON-LD review extraction shape.

The URL may 404 once BestBuy retires the model; refresh by re-running
``scripts/bestbuy/probe_posture.py`` against a current search page and
picking a fresh SKU.
"""

from __future__ import annotations

import os

import pytest

from scrapers_lib.core.schemas import Anchor, AttributionRegex
from scrapers_lib.tier3.bestbuy import fetch_bestbuy_reviews

LIVE = bool(os.environ.get("SCRAPERSLIB_LIVE_TESTS"))

ALIENWARE_URL = (
    "https://www.bestbuy.com/site/alienware-area-51/6628371.p?skuId=6628371"
)


def _area51_anchor() -> Anchor:
    return Anchor(
        anchor_id="alienware_area_51_18",
        anchor_type="product",
        name="Alienware Area-51 18",
        attribution_regex=AttributionRegex(primary=["Alienware", "Area-51"]),
        source_urls={"bestbuy": ALIENWARE_URL},
    )


@pytest.mark.skipif(not LIVE, reason="live tests disabled; set SCRAPERSLIB_LIVE_TESTS=1")
def test_fetch_bestbuy_reviews_live():
    """Default path: PDP inline reviews."""
    mentions = fetch_bestbuy_reviews(ALIENWARE_URL, anchors=[_area51_anchor()])

    # BestBuy inlines ~5 reviews on an active PDP; an active listing
    # with at least a few reviews should yield non-empty output.
    assert len(mentions) >= 1, (
        "no reviews returned — PDP may have changed or listing retired; "
        "update ALIENWARE_URL in this file"
    )
    for m in mentions:
        assert m.source == "bestbuy"
        assert m.source_type == "post"
        assert m.attribution.anchor_id == "alienware_area_51_18"
        assert m.raw_text.strip()
        assert m.parent_id == "6628371"


@pytest.mark.skipif(not LIVE, reason="live tests disabled; set SCRAPERSLIB_LIVE_TESTS=1")
def test_fetch_bestbuy_reviews_paginate_live():
    """Wave 2d: paginated path returns more reviews than the PDP inline + dates."""
    # Cap max_pages=2 to keep the live-integration runtime polite
    # (~8-10 seconds total: warm + 2 pages + 3-second delay between).
    mentions = fetch_bestbuy_reviews(
        ALIENWARE_URL,
        anchors=[_area51_anchor()],
        paginate=True,
        max_pages=2,
    )

    # Two pages × 20 reviews per page = up to 40. Accept ≥10 to tolerate
    # churn / early termination if the SKU has fewer reviews than at
    # fixture-capture time.
    assert len(mentions) >= 10, (
        f"paginate=True returned only {len(mentions)} reviews — expected "
        f"≥10 across 2 pages. Upstream shape may have changed; "
        f"re-run scripts/bestbuy/probe_reviews_pagination.py."
    )

    # Wave 2d's headline: published_at populated on every review.
    dated = [m for m in mentions if m.published_at is not None]
    assert len(dated) == len(mentions), (
        f"{len(mentions) - len(dated)} reviews missing published_at — "
        f"date extraction broken. Inspect the <time class='submission-date' "
        f"title='...'> selector in tier3/bestbuy.py."
    )

    for m in mentions:
        assert m.source == "bestbuy"
        assert m.source_type == "post"
        assert m.attribution.anchor_id == "alienware_area_51_18"
        assert m.raw_text.strip()
        assert m.parent_id == "6628371"
